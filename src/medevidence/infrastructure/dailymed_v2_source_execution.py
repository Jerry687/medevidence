"""Durable current-label DailyMed V2 discovery, enrichment and selected SPL."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self, final

import httpx
from pydantic import StringConstraints, model_validator

from medevidence.connectors.dailymed import (
    DailyMedConnector,
    DailyMedConnectorConfig,
    DailyMedOperation,
    DailyMedRequest,
    build_dailymed_request,
    validate_dailymed_request,
)
from medevidence.connectors.dailymed.client import RawDailyMedResponse
from medevidence.connectors.dailymed.enrichment import (
    parse_discovery_page_v2,
    parse_packaging_page,
    project_discovery_summaries_v2,
)
from medevidence.connectors.dailymed.parsing import (
    parse_source_native_spl_document,
)
from medevidence.connectors.dailymed.policy import validate_dailymed_url
from medevidence.domain import (
    CoverageStatus,
    DailyMedSelectionMode,
    ExecutionBounds,
    ExecutionStatus,
    M1BResearchRequestV1,
    ResearchScope,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryGroupV2,
    DailyMedDiscoverySummaryV2,
    DailyMedEnrichedCandidateV2,
    DailyMedEnrichmentReason,
    DailyMedEnrichmentStatus,
    DailyMedPackagingExecutionV2,
    DailyMedRawParentV2,
    DailyMedSelectionDecisionV2,
)
from medevidence.domain.dailymed_v2_execution import (
    DailyMedV2PackagingResult,
    DailyMedV2SectionRef,
    DailyMedV2SelectedSplRecord,
    DailyMedV2SelectedSplResult,
)
from medevidence.domain.identifiers import DurableModel
from medevidence.ingestion.dailymed_v2_artifacts import (
    CapturedDailyMedV2,
    DailyMedV2Manifest,
    DailyMedV2Member,
    DailyMedV2Observation,
    capture_dailymed_v2,
    replay_dailymed_v2,
)
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.orchestration.contracts import (
    MAX_SOURCE_TASK_ATTEMPTS,
    source_task_attempt,
    source_task_id,
)
from medevidence.persistence import PersistenceRepository
from medevidence.persistence.dailymed_v2 import (
    DailyMedV2MemberInput,
    DailyMedV2RecordInput,
    DailyMedV2Repository,
)
from medevidence.persistence.repositories import M1BAcquisitionLifecycle, M1BRunLifecycle
from medevidence.tools.contracts import DailyMedDiscoveryRequest
from medevidence.tools.dailymed_enrichment import (
    DailyMedPackagingRequestV2,
    build_enriched_candidate,
    plan_dailymed_enrichment_groups,
    select_enriched_candidates,
    unavailable_enrichment_decision,
)
from medevidence.tools.dailymed_v2_material import (
    DailyMedV2EvidenceChunk,
    admit_dailymed_v2_task_chunks,
    build_dailymed_v2_chunks,
)

from .dailymed_v2_record_store import DailyMedV2RecordStore, LoadedDailyMedV2Record

_RUN = re.compile(r"^run:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_BOUNDS = ExecutionBounds(
    max_query_characters=512,
    max_pages=5,
    max_records=100,
    max_payload_bytes=5_242_880,
    max_total_seconds=30,
)


class DailyMedV2ExecutionUnavailable(RuntimeError):
    """Stable no-resend or unsupported-current-label state."""


class DailyMedNativeDiscoveryRequestPort(Protocol):
    def resolve(self, request: DailyMedDiscoveryRequest) -> DailyMedRequest: ...


class DailyMedV2SourceIntent(DurableModel):
    marker: Literal["M3_DAILYMED_V2_SOURCE_INTENT"] = "M3_DAILYMED_V2_SOURCE_INTENT"
    intent_id: Annotated[
        str, StringConstraints(pattern=r"^acquisition-intent:sha256:[0-9a-f]{64}$")
    ]
    run_id: str
    scope_id: str
    task_id: str
    attempt_id: str
    acquisition_id: str
    acquisition_ordinal: int
    operation: Literal["discovery", "packaging", "selected_spl"]
    query_id: str
    request_identity: str
    request_url: str
    selected_setid: str | None = None
    selected_spl_version: str | None = None
    created_at_utc: datetime
    code_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]

    @model_validator(mode="after")
    def exact_intent(self) -> Self:
        offset = self.created_at_utc.utcoffset()
        if (
            not 0 <= self.acquisition_ordinal <= 7
            or offset is None
            or offset.total_seconds() != 0
            or not self.request_url.startswith("https://dailymed.nlm.nih.gov/")
            or self.request_identity
            != sha256_digest(
                canonical_json(
                    {
                        "operation": self.operation,
                        "request_url": self.request_url,
                        "selected_setid": self.selected_setid,
                        "selected_spl_version": self.selected_spl_version,
                    }
                )
            )
        ):
            raise ValueError("DailyMed V2 source intent fields differ")
        expected = derive_identity(
            "acquisition-intent",
            {
                "run_id": self.run_id,
                "scope_id": self.scope_id,
                "task_id": self.task_id,
                "attempt_id": self.attempt_id,
                "acquisition_ordinal": self.acquisition_ordinal,
                "operation": self.operation,
                "query_id": self.query_id,
                "request_identity": self.request_identity,
                "code_revision": self.code_revision,
            },
        )
        if self.intent_id != expected:
            raise ValueError("DailyMed V2 source intent identity differs")
        return self

    def canonical_bytes(self) -> bytes:
        raw = canonical_json(self).encode("utf-8")
        if len(raw) > 65_536:
            raise ValueError("DailyMed V2 source intent exceeds 64 KiB")
        return raw


@dataclass(frozen=True, slots=True)
class DailyMedV2RunResult:
    groups: tuple[DailyMedDiscoveryGroupV2, ...]
    packaging: tuple[DailyMedV2PackagingResult, ...]
    decisions: tuple[DailyMedSelectionDecisionV2, ...]
    selected_spl: tuple[DailyMedV2SelectedSplRecord, ...]
    evidence_chunks: tuple[DailyMedV2EvidenceChunk, ...]
    review_reason_codes: tuple[str, ...]


@final
class DailyMedV2SourceExecutionBridge:
    """Execute each bounded current-label operation only after durable START."""

    def __init__(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        request: M1BResearchRequestV1,
        task_id: str,
        attempt_id: str,
        clock: Callable[[], datetime],
        code_revision: str,
        native_requests: DailyMedNativeDiscoveryRequestPort,
        transport_factory: Callable[[], httpx.BaseTransport],
        snapshots: SnapshotStore,
        repository: PersistenceRepository,
    ) -> None:
        if (
            type(run_id) is not str
            or _RUN.fullmatch(run_id) is None
            or type(scope) is not ResearchScope
            or type(request) is not M1BResearchRequestV1
            or type(snapshots) is not SnapshotStore
            or type(repository) is not PersistenceRepository
            or _REVISION.fullmatch(code_revision) is None
        ):
            raise ValueError("DailyMed V2 bridge context is invalid")
        exact_scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        exact_request = M1BResearchRequestV1.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        if (
            exact_scope != scope
            or exact_request != request
            or exact_request.scope != scope
            or SourceType.DAILYMED not in request.requested_sources
            or scope.date_range is not None
            or any(
                item.selection_mode is not DailyMedSelectionMode.STRICT_IDENTITY
                for item in request.dailymed_selection_requests
            )
            or scope.query_bounds.max_query_characters < 512
            or scope.query_bounds.max_pages < 5
            or scope.query_bounds.max_total_seconds < 30
            or scope.result_bounds.max_records < 100
            or scope.result_bounds.max_payload_bytes < 5_242_880
            or task_id != source_task_id(run_id, SourceType.DAILYMED)
            or attempt_id
            not in {
                source_task_attempt(task_id, number).attempt_id
                for number in range(1, MAX_SOURCE_TASK_ATTEMPTS + 1)
            }
        ):
            raise DailyMedV2ExecutionUnavailable("dailymed_v2_scope_or_task_unavailable")
        self._run_id = run_id
        self._scope_id = scope.scope_id
        self._request = exact_request
        self._task_id = task_id
        self._attempt_id = attempt_id
        self._clock = clock
        self._code_revision = code_revision
        self._native = native_requests
        self._transport_factory = transport_factory
        self._snapshots = snapshots
        self._repository = repository
        self._records = DailyMedV2RecordStore(
            snapshots=snapshots, repository=DailyMedV2Repository(repository)
        )

    def _now(self) -> datetime:
        value = self._clock()
        offset = value.utcoffset() if type(value) is datetime and value.tzinfo else None
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("DailyMed V2 clock must return exact UTC")
        return value

    def _new_connector(self) -> DailyMedConnector:
        transport = self._transport_factory()
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("DailyMed V2 transport factory returned invalid transport")
        return DailyMedConnector(transport, DailyMedConnectorConfig(), utc_now=self._clock)

    def _intent_path(self, intent_id: str) -> Path:
        run = _RUN.fullmatch(self._run_id)
        assert run is not None
        digest = intent_id.removeprefix("acquisition-intent:sha256:")
        if len(digest) != 64 or any(item not in "0123456789abcdef" for item in digest):
            raise SnapshotIntegrityError("DailyMed V2 intent ID is invalid")
        return (
            self._snapshots.root
            / "journal"
            / run.group(1)
            / "source-execution"
            / "dailymed-v2"
            / digest
            / "intent.json"
        )

    def _load_intent(self, intent_id: str) -> DailyMedV2SourceIntent:
        target = self._intent_path(intent_id)
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if not target.is_file() or not 1 <= target.stat().st_size <= 65_536:
            raise SnapshotIntegrityError("DailyMed V2 source intent is missing")
        size = target.stat().st_size
        with target.open("rb") as handle:
            raw = handle.read(65_537)
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if len(raw) != size or len(raw) > 65_536:
            raise SnapshotIntegrityError("DailyMed V2 source intent changed during read")
        parsed = DailyMedV2SourceIntent.model_validate_json(raw, strict=False)
        exact = DailyMedV2SourceIntent.model_validate(parsed.model_dump(mode="python"), strict=True)
        if exact.canonical_bytes() != raw or exact.intent_id != intent_id:
            raise SnapshotIntegrityError("DailyMed V2 source intent is noncanonical")
        return exact

    def _begin(
        self,
        *,
        operation: Literal["discovery", "packaging", "selected_spl"],
        ordinal: int,
        query_id: str,
        native: DailyMedRequest,
        selected_setid: str | None = None,
        selected_spl_version: str | None = None,
    ) -> tuple[DailyMedV2SourceIntent, M1BAcquisitionLifecycle, bool]:
        native = validate_dailymed_request(native)
        request_identity = sha256_digest(
            canonical_json(
                {
                    "operation": operation,
                    "request_url": native.url,
                    "selected_setid": selected_setid,
                    "selected_spl_version": selected_spl_version,
                }
            )
        )
        intent_id = derive_identity(
            "acquisition-intent",
            {
                "run_id": self._run_id,
                "scope_id": self._scope_id,
                "task_id": self._task_id,
                "attempt_id": self._attempt_id,
                "acquisition_ordinal": ordinal,
                "operation": operation,
                "query_id": query_id,
                "request_identity": request_identity,
                "code_revision": self._code_revision,
            },
        )
        acquisition_id = derive_identity(
            "acquisition", {"run_id": self._run_id, "intent_id": intent_id}
        )
        existing_run = self._repository.get_m1b_run_lifecycle(self._run_id)
        started = self._now()
        if existing_run is None:
            self._repository.begin_m1b_run(
                M1BRunLifecycle(
                    run_id=self._run_id,
                    request_id=self._request.request_id,
                    scope_id=self._scope_id,
                    status="running",
                    created_at_utc=started,
                    completed_at_utc=None,
                )
            )
        elif (
            existing_run.request_id != self._request.request_id
            or existing_run.scope_id != self._scope_id
        ):
            raise SnapshotIntegrityError("DailyMed V2 stored run belongs to another request")
        elif existing_run.status != "running" and (
            self._repository.get_m1b_acquisition_lifecycle(acquisition_id) is None
        ):
            raise DailyMedV2ExecutionUnavailable("dailymed_v2_run_already_terminal")
        lifecycle = M1BAcquisitionLifecycle(
            acquisition_intent_id=intent_id,
            acquisition_ordinal=ordinal,
            attempt_id=self._attempt_id,
            run_id=self._run_id,
            acquisition_id=acquisition_id,
            source="dailymed",
            operation={"discovery": "search", "packaging": "packaging", "selected_spl": "fetch"}[
                operation
            ],
            request_identity=request_identity,
            query_id=query_id,
            execution_profile_id="DAILYMED_M1B_CONSTRAINED_V1",
            started_at_utc=started,
            completed_at_utc=None,
            schema_version="m1b.acquisition.v1",
        )
        stored, created = self._repository.begin_m1b_acquisition(lifecycle)
        if not created:
            intent = self._load_intent(intent_id)
            if (
                stored.completed_at_utc is None
                or intent.acquisition_id != acquisition_id
                or intent.query_id != query_id
                or intent.request_identity != request_identity
                or intent.request_url != native.url
            ):
                raise DailyMedV2ExecutionUnavailable("dailymed_v2_started_state_unknown")
            return intent, stored, False
        intent = DailyMedV2SourceIntent(
            intent_id=intent_id,
            run_id=self._run_id,
            scope_id=self._scope_id,
            task_id=self._task_id,
            attempt_id=self._attempt_id,
            acquisition_id=acquisition_id,
            acquisition_ordinal=ordinal,
            operation=operation,
            query_id=query_id,
            request_identity=request_identity,
            request_url=native.url,
            selected_setid=selected_setid,
            selected_spl_version=selected_spl_version,
            created_at_utc=started,
            code_revision=self._code_revision,
        )
        target = self._intent_path(intent_id)
        with SnapshotStore.writer(self._snapshots):
            SnapshotStore.publish_bytes(
                self._snapshots,
                target.relative_to(self._snapshots.root).as_posix(),
                intent.canonical_bytes(),
                artifact_class="journal",
            )
        if self._load_intent(intent_id) != intent:
            raise SnapshotIntegrityError("DailyMed V2 START intent readback differs")
        return intent, stored, True

    @staticmethod
    def _observations(
        responses: tuple[RawDailyMedResponse, ...],
    ) -> tuple[DailyMedV2Observation, ...]:
        return tuple(
            DailyMedV2Observation(
                body=item.body,
                status_code=item.status_code,
                observed_at_utc=item.observed_at_utc,
                request_url=item.request_url,
                final_url=item.final_url,
                media_type=dict(item.headers).get("content-type", "application/octet-stream"),
                page_number=item.page_number,
                attempt_count=item.attempt_count,
                body_complete=item.body_complete,
                termination_reason=item.termination_reason,
            )
            for item in responses
        )

    @staticmethod
    def _outcome(
        query_id: str,
        *,
        count: int,
        pages: int,
        truncated: bool,
        failed: bool,
        has_raw: bool,
        failure_code: str | None,
    ) -> SourceOutcome:
        coverage = (
            (CoverageStatus.PARTIAL if has_raw else CoverageStatus.UNAVAILABLE)
            if failed
            else (CoverageStatus.PARTIAL if truncated else CoverageStatus.COMPLETE)
        )
        result = (
            ResultStatus.MATCHES
            if count
            else ResultStatus.NO_MATCH
            if coverage is CoverageStatus.COMPLETE
            else ResultStatus.INDETERMINATE
        )
        return SourceOutcome(
            source=SourceType.DAILYMED,
            query_id=query_id,
            execution_status=ExecutionStatus.FAILED if failed else ExecutionStatus.SUCCEEDED,
            coverage_status=coverage,
            result_status=result,
            configured_bounds=_BOUNDS,
            valid_result_count=count,
            pages_completed=pages,
            truncated=truncated,
            warning_codes=() if coverage is CoverageStatus.COMPLETE else ("incomplete_coverage",),
            failure_id=(
                derive_identity("source-failure", {"query_id": query_id, "code": failure_code})
                if failed
                else None
            ),
        )

    def _capture(
        self,
        intent: DailyMedV2SourceIntent,
        lifecycle: M1BAcquisitionLifecycle,
        outcome: SourceOutcome,
        responses: tuple[RawDailyMedResponse, ...],
        *,
        requests_sent: int,
        pages_completed: int,
        completed: datetime,
        stable_spl_bytes: bytes | None = None,
    ) -> CapturedDailyMedV2:
        observations = self._observations(responses)
        snapshot_id = derive_identity(
            "snapshot",
            {"run_id": self._run_id, "acquisition_intent_id": intent.intent_id},
        )
        with SnapshotStore.writer(self._snapshots):
            captured = capture_dailymed_v2(
                self._snapshots,
                operation=intent.operation,
                run_id=self._run_id,
                acquisition_id=intent.acquisition_id,
                acquisition_intent_id=intent.intent_id,
                acquisition_ordinal=intent.acquisition_ordinal,
                attempt_id=self._attempt_id,
                query_id=intent.query_id,
                snapshot_id=snapshot_id,
                request_identity=intent.request_identity,
                started_at_utc=lifecycle.started_at_utc,
                completed_at_utc=completed,
                source_outcome=outcome,
                requests_sent=requests_sent,
                pages_completed=pages_completed,
                observations=observations,
                stable_spl_bytes=stable_spl_bytes,
                selected_setid=intent.selected_setid,
                selected_spl_version=intent.selected_spl_version,
                code_revision=self._code_revision,
            )
        if (
            replay_dailymed_v2(
                self._snapshots,
                manifest_id=captured.manifest.manifest_id,
                expected_operation=intent.operation,
                expected_run_id=self._run_id,
                expected_acquisition_id=intent.acquisition_id,
                expected_intent_id=intent.intent_id,
                expected_query_id=intent.query_id,
                expected_request_identity=intent.request_identity,
            )
            != captured.manifest
        ):
            raise SnapshotIntegrityError("DailyMed V2 captured manifest readback differs")
        return captured

    def _persist_source_rows(
        self,
        lifecycle: M1BAcquisitionLifecycle,
        captured: CapturedDailyMedV2,
    ) -> None:
        manifest = captured.manifest
        repository = self._repository
        v2_repository = DailyMedV2Repository(repository)
        completed = manifest.completed_at_utc
        repository.insert_or_verify_m1b_artifact(
            {
                "artifact_id": manifest.manifest_id,
                "artifact_kind": "dailymed_v2_manifest",
                "source_partition": "dailymed",
                "content_hash": manifest.manifest_id,
                "byte_size": len(manifest.canonical_bytes()),
                "media_type": "application/json",
                "relative_storage_label": captured.manifest_path.relative_to(
                    self._snapshots.root
                ).as_posix(),
                "schema_version": manifest.manifest_schema_version,
                "created_at_utc": completed,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
            }
        )
        for member in manifest.members:
            if member.kind == "dailymed_spl_xml":
                # Current XML can be byte-identical to its raw HTTP response. The
                # versioned manifest binds this separate role-specific file path.
                continue
            artifact_row = {
                "artifact_id": member.artifact_id,
                "artifact_kind": member.kind,
                "source_partition": "dailymed",
                "content_hash": member.content_hash,
                "byte_size": member.byte_size,
                "media_type": member.media_type,
                "relative_storage_label": member.relative_path,
                "schema_version": "m3.dailymed-v2.raw-response.v1",
                "created_at_utc": completed,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
            }
            existing_artifact = v2_repository.get_artifact(member.artifact_id)
            if existing_artifact is not None:
                if any(
                    existing_artifact.get(name) != expected
                    for name, expected in artifact_row.items()
                    if name != "created_at_utc"
                ):
                    raise SnapshotIntegrityError("DailyMed V2 shared raw artifact role differs")
                artifact_row["created_at_utc"] = existing_artifact["created_at_utc"]
            repository.insert_or_verify_m1b_artifact(artifact_row)
        repository.insert_or_verify_m1b(
            "m1b_snapshots",
            {
                "query_id": lifecycle.query_id,
                "acquisition_intent_id": lifecycle.acquisition_intent_id,
                "acquisition_ordinal": lifecycle.acquisition_ordinal,
                "attempt_id": lifecycle.attempt_id,
                "run_id": lifecycle.run_id,
                "snapshot_id": manifest.snapshot_id,
                "acquisition_id": lifecycle.acquisition_id,
                "source": "dailymed",
                "manifest_artifact_id": manifest.manifest_id,
                "retrieved_at_utc": completed,
                "connector_version": "m1b-dm-002",
                "schema_version": "m3.dailymed-v2.snapshot.v1",
            },
        )
        for member in manifest.members:
            if member.kind != "dailymed_http_response":
                continue
            assert member.page_number is not None
            assert member.attempt_count is not None
            assert member.request_url is not None
            assert member.final_url is not None
            v2_repository.save_member(
                DailyMedV2MemberInput(
                    run_id=lifecycle.run_id,
                    acquisition_id=lifecycle.acquisition_id,
                    snapshot_id=manifest.snapshot_id,
                    ordinal=member.ordinal,
                    link_id=member.link_id,
                    artifact_id=member.artifact_id,
                    content_hash=member.content_hash,
                    relative_path=member.relative_path,
                    byte_size=member.byte_size,
                    media_type=member.media_type,
                    http_status=member.http_status,
                    observed_at_utc=member.observed_at_utc,
                    body_complete=member.body_complete,
                    termination_reason=member.termination_reason,
                    page_number=member.page_number,
                    attempt_count=member.attempt_count,
                    request_url=member.request_url,
                    final_url=member.final_url,
                )
            )
        source_outcome = manifest.source_outcome
        bounds = source_outcome.configured_bounds
        repository.insert_or_verify_m1b(
            "m1b_source_outcomes",
            {
                "source_outcome_id": derive_identity(
                    "source-outcome",
                    {
                        "run_id": lifecycle.run_id,
                        "acquisition_id": lifecycle.acquisition_id,
                        "operation": lifecycle.operation,
                        "outcome": source_outcome,
                    },
                ),
                "snapshot_id": manifest.snapshot_id,
                "run_id": lifecycle.run_id,
                "query_id": lifecycle.query_id,
                "acquisition_id": lifecycle.acquisition_id,
                "source": "dailymed",
                "acquisition_intent_id": lifecycle.acquisition_intent_id,
                "acquisition_ordinal": lifecycle.acquisition_ordinal,
                "operation": lifecycle.operation,
                "execution_status": source_outcome.execution_status.value,
                "coverage_status": source_outcome.coverage_status.value,
                "result_status": source_outcome.result_status.value,
                "max_query_characters": bounds.max_query_characters,
                "max_pages": bounds.max_pages,
                "max_records": bounds.max_records,
                "max_payload_bytes": bounds.max_payload_bytes,
                "max_total_seconds": bounds.max_total_seconds,
                "valid_result_count": source_outcome.valid_result_count,
                "pages_completed": source_outcome.pages_completed,
                "truncated": source_outcome.truncated,
                "failure_id": source_outcome.failure_id,
                "warning_codes": list(source_outcome.warning_codes),
                "schema_version": "1.0",
            },
        )

    def _record_input(
        self,
        *,
        kind: Literal["discovery", "packaging", "decision", "selected_spl", "chunk"],
        intent: DailyMedV2SourceIntent,
        manifest: DailyMedV2Manifest,
        payload: object,
        item_ordinal: int = 0,
    ) -> DailyMedV2RecordInput:
        return DailyMedV2RecordInput(
            record_kind=kind,
            run_id=self._run_id,
            scope_id=self._scope_id,
            task_id=self._task_id,
            attempt_id=self._attempt_id,
            query_id=intent.query_id,
            acquisition_id=intent.acquisition_id,
            acquisition_intent_id=intent.intent_id,
            snapshot_id=manifest.snapshot_id,
            manifest_id=manifest.manifest_id,
            item_ordinal=item_ordinal,
            payload_bytes=canonical_json(payload).encode("utf-8"),
            created_at_utc=manifest.completed_at_utc,
        )

    def _load_completed(
        self,
        *,
        kind: Literal["discovery", "packaging", "selected_spl"],
        intent: DailyMedV2SourceIntent,
        lifecycle: M1BAcquisitionLifecycle,
        native: DailyMedRequest,
    ) -> LoadedDailyMedV2Record:
        loaded = self._records.load_slot(
            run_id=self._run_id,
            attempt_id=self._attempt_id,
            record_kind=kind,
            query_id=intent.query_id,
        )
        if loaded is None or (
            loaded.record.acquisition_id != intent.acquisition_id
            or loaded.record.acquisition_intent_id != intent.intent_id
            or loaded.record.created_at_utc != lifecycle.completed_at_utc
        ):
            raise SnapshotIntegrityError("DailyMed V2 completed source record is missing")
        manifest = replay_dailymed_v2(
            self._snapshots,
            manifest_id=loaded.record.manifest_id,
            expected_operation=intent.operation,
            expected_run_id=self._run_id,
            expected_acquisition_id=intent.acquisition_id,
            expected_intent_id=intent.intent_id,
            expected_query_id=intent.query_id,
            expected_request_identity=intent.request_identity,
        )
        if (
            manifest.started_at_utc != lifecycle.started_at_utc
            or manifest.completed_at_utc != lifecycle.completed_at_utc
            or manifest.attempt_id != self._attempt_id
            or manifest.acquisition_ordinal != lifecycle.acquisition_ordinal
        ):
            raise SnapshotIntegrityError("DailyMed V2 completed source context differs")
        self._verify_pg_graph(manifest, lifecycle)
        native = validate_dailymed_request(native)
        for member in manifest.members:
            if member.kind != "dailymed_http_response":
                continue
            assert member.page_number is not None
            expected = (
                native.with_page(member.page_number)
                if intent.operation in ("discovery", "packaging")
                else native
            )
            if member.request_url != expected.url or member.final_url is None:
                raise SnapshotIntegrityError("DailyMed V2 raw request URL differs")
            try:
                validate_dailymed_url(member.final_url, expected)
            except ValueError as error:
                raise SnapshotIntegrityError("DailyMed V2 final URL differs") from error
        if type(loaded.payload) is DailyMedDiscoveryGroupV2:
            self._verify_discovery_payload(loaded.payload, manifest)
        elif type(loaded.payload) is DailyMedV2PackagingResult:
            self._verify_packaging_payload(loaded.payload, manifest)
        elif (
            type(loaded.payload) is DailyMedV2SelectedSplResult
            and loaded.payload.source_outcome != manifest.source_outcome
        ):
            raise SnapshotIntegrityError("DailyMed V2 selected outcome differs")
        return loaded

    def _verify_pg_graph(
        self, manifest: DailyMedV2Manifest, lifecycle: M1BAcquisitionLifecycle
    ) -> None:
        graph = DailyMedV2Repository(self._repository).load_source_graph(
            run_id=self._run_id,
            acquisition_id=lifecycle.acquisition_id,
            query_id=lifecycle.query_id,
            snapshot_id=manifest.snapshot_id,
        )
        if graph is None:
            raise SnapshotIntegrityError("DailyMed V2 PostgreSQL source graph is missing")
        acquisition = graph["acquisition"]
        snapshot = graph["snapshot"]
        outcome = graph["outcome"]
        members = graph["membership"]
        artifacts = graph["artifacts"]
        if (
            not isinstance(acquisition, dict)
            or not isinstance(snapshot, dict)
            or not isinstance(outcome, dict)
            or not isinstance(members, tuple)
            or not isinstance(artifacts, tuple)
            or acquisition.get("acquisition_intent_id") != manifest.acquisition_intent_id
            or acquisition.get("attempt_id") != self._attempt_id
            or acquisition.get("acquisition_ordinal") != manifest.acquisition_ordinal
            or acquisition.get("request_identity") != manifest.request_identity
            or acquisition.get("completed_at_utc") != manifest.completed_at_utc
            or snapshot.get("manifest_artifact_id") != manifest.manifest_id
            or snapshot.get("retrieved_at_utc") != manifest.completed_at_utc
            or outcome.get("source_outcome_id")
            != derive_identity(
                "source-outcome",
                {
                    "run_id": lifecycle.run_id,
                    "acquisition_id": lifecycle.acquisition_id,
                    "operation": lifecycle.operation,
                    "outcome": manifest.source_outcome,
                },
            )
            or outcome.get("execution_status") != manifest.source_outcome.execution_status.value
            or outcome.get("coverage_status") != manifest.source_outcome.coverage_status.value
            or outcome.get("result_status") != manifest.source_outcome.result_status.value
            or outcome.get("valid_result_count") != manifest.source_outcome.valid_result_count
            or outcome.get("pages_completed") != manifest.pages_completed
            or outcome.get("truncated") != manifest.source_outcome.truncated
            or outcome.get("warning_codes") != list(manifest.source_outcome.warning_codes)
            or outcome.get("failure_id") != manifest.source_outcome.failure_id
        ):
            raise SnapshotIntegrityError("DailyMed V2 PostgreSQL source graph differs")
        raw_members = tuple(
            item for item in manifest.members if item.kind == "dailymed_http_response"
        )
        if len(members) != len(raw_members):
            raise SnapshotIntegrityError("DailyMed V2 PostgreSQL raw membership differs")
        artifact_map = {row.get("artifact_id"): row for row in artifacts if isinstance(row, dict)}
        manifest_artifact = artifact_map.get(manifest.manifest_id)
        if (
            not isinstance(manifest_artifact, dict)
            or manifest_artifact.get("content_hash") != manifest.manifest_id
            or manifest_artifact.get("artifact_kind") != "dailymed_v2_manifest"
            or manifest_artifact.get("byte_size") != len(manifest.canonical_bytes())
        ):
            raise SnapshotIntegrityError("DailyMed V2 PostgreSQL manifest artifact differs")
        for member, row in zip(raw_members, members, strict=True):
            artifact = artifact_map.get(member.artifact_id)
            if (
                not isinstance(row, dict)
                or not isinstance(artifact, dict)
                or any(
                    row.get(name) != expected
                    for name, expected in (
                        ("run_id", self._run_id),
                        ("acquisition_id", lifecycle.acquisition_id),
                        ("snapshot_id", manifest.snapshot_id),
                        ("ordinal", member.ordinal),
                        ("link_id", member.link_id),
                        ("artifact_id", member.artifact_id),
                        ("content_hash", member.content_hash),
                        ("relative_path", member.relative_path),
                        ("byte_size", member.byte_size),
                        ("media_type", member.media_type),
                        ("http_status", member.http_status),
                        ("observed_at_utc", member.observed_at_utc),
                        ("body_complete", member.body_complete),
                        ("termination_reason", member.termination_reason),
                        ("page_number", member.page_number),
                        ("attempt_count", member.attempt_count),
                        ("request_url", member.request_url),
                        ("final_url", member.final_url),
                    )
                )
                or artifact.get("artifact_kind") != "dailymed_http_response"
                or artifact.get("relative_storage_label") != member.relative_path
                or artifact.get("content_hash") != member.content_hash
                or artifact.get("byte_size") != member.byte_size
            ):
                raise SnapshotIntegrityError("DailyMed V2 PostgreSQL ordered member differs")

    def _member_bytes(self, member: DailyMedV2Member) -> bytes:
        relative = member.relative_path
        target = self._snapshots.root.joinpath(*relative.split("/"))
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if not target.is_file() or not 0 <= target.stat().st_size <= 5_242_880:
            raise SnapshotIntegrityError("DailyMed V2 raw member is missing or oversized")
        size = target.stat().st_size
        with target.open("rb") as handle:
            raw = handle.read(5_242_881)
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if (
            len(raw) != size
            or len(raw) != member.byte_size
            or sha256_digest(raw) != member.content_hash
        ):
            raise SnapshotIntegrityError("DailyMed V2 raw member bytes differ")
        return raw

    def _verify_discovery_payload(
        self, group: DailyMedDiscoveryGroupV2, manifest: DailyMedV2Manifest
    ) -> None:
        if group.outcome != manifest.source_outcome:
            raise SnapshotIntegrityError("DailyMed V2 discovery outcome differs")
        summaries: list[DailyMedDiscoverySummaryV2] = []
        for page_number in range(1, manifest.pages_completed + 1):
            complete = tuple(
                member
                for member in manifest.members
                if member.kind == "dailymed_http_response"
                and member.page_number == page_number
                and member.http_status == 200
                and member.body_complete
            )
            if len(complete) != 1:
                raise SnapshotIntegrityError("DailyMed V2 discovery page raw is ambiguous")
            member = complete[0]
            raw = self._member_bytes(member)
            page = parse_discovery_page_v2(raw, expected_page=page_number)
            summaries.extend(
                project_discovery_summaries_v2(
                    raw,
                    parent=self._raw_parent(manifest, member.ordinal, kind="discovery_json"),
                    expected_page=page_number,
                    expected_pagesize=page.pagesize,
                    first_ordinal=len(summaries),
                )
            )
        if group.summaries != tuple(summaries):
            raise SnapshotIntegrityError("DailyMed V2 discovery summaries differ from raw")

    def _verify_packaging_payload(
        self, payload: DailyMedV2PackagingResult, manifest: DailyMedV2Manifest
    ) -> None:
        if payload.source_outcome != manifest.source_outcome:
            raise SnapshotIntegrityError("DailyMed V2 packaging outcome differs")
        retained = []
        for number in range(1, manifest.pages_completed + 1):
            complete = tuple(
                item
                for item in manifest.members
                if item.kind == "dailymed_http_response"
                and item.page_number == number
                and item.http_status == 200
                and item.body_complete
            )
            if len(complete) != 1:
                raise SnapshotIntegrityError("DailyMed V2 packaging page raw is ambiguous")
            retained.append(
                parse_packaging_page(
                    self._member_bytes(complete[0]),
                    expected_setid=payload.setid,
                    expected_spl_version=payload.expected_current_spl_version,
                    expected_page=number,
                )
            )
        retained_count = sum(len(page.products) for page in retained)
        if retained_count != payload.source_outcome.valid_result_count:
            raise SnapshotIntegrityError("DailyMed V2 packaging partial count differs")
        if payload.execution is None:
            if (
                payload.reason is DailyMedEnrichmentReason.ENRICHMENT_PAGINATION_UNSUPPORTED
                and manifest.pages_completed <= 1
                and not manifest.source_outcome.truncated
            ):
                raise SnapshotIntegrityError("DailyMed V2 pagination reason differs")
            return
        parent = payload.execution.parent
        if parent.member_ordinal >= len(manifest.members):
            raise SnapshotIntegrityError("DailyMed V2 packaging parent ordinal differs")
        member = manifest.members[parent.member_ordinal]
        if (
            member.kind != "dailymed_http_response"
            or member.content_hash != parent.raw_content_hash
            or member.link_id != parent.link_id
            or member.byte_size != parent.byte_size
            or manifest.pages_completed != 1
        ):
            raise SnapshotIntegrityError("DailyMed V2 packaging parent differs")
        page = parse_packaging_page(
            self._member_bytes(member),
            expected_setid=payload.setid,
            expected_spl_version=payload.expected_current_spl_version,
            expected_page=1,
        )
        if page.next_page is not None or page.products != payload.execution.products:
            raise SnapshotIntegrityError("DailyMed V2 packaging products differ from raw")

    def _raw_parent(
        self,
        manifest: DailyMedV2Manifest,
        member_ordinal: int,
        *,
        kind: Literal["discovery_json", "packaging_json"],
    ) -> DailyMedRawParentV2:
        member = manifest.members[member_ordinal]
        if member.kind != "dailymed_http_response" or not member.body_complete:
            raise SnapshotIntegrityError("DailyMed V2 candidate parent is not complete raw")
        return DailyMedRawParentV2(
            kind=kind,
            run_id=self._run_id,
            attempt_id=self._attempt_id,
            acquisition_id=manifest.acquisition_id,
            acquisition_ordinal=manifest.acquisition_ordinal,
            acquisition_intent_id=manifest.acquisition_intent_id,
            query_id=manifest.query_id,
            snapshot_id=manifest.snapshot_id,
            manifest_id=manifest.manifest_id,
            member_ordinal=member.ordinal,
            link_id=member.link_id,
            raw_artifact_id=member.artifact_id,
            raw_content_hash=member.content_hash,
            byte_size=member.byte_size,
        )

    def _discovery(
        self, request: DailyMedDiscoveryRequest, ordinal: int
    ) -> tuple[DailyMedDiscoveryGroupV2, DailyMedV2RecordInput]:
        native = validate_dailymed_request(self._native.resolve(request))
        if native.operation is not DailyMedOperation.DISCOVERY:
            raise ValueError("DailyMed V2 native resolver returned a non-discovery request")
        intent, lifecycle, created = self._begin(
            operation="discovery",
            ordinal=ordinal,
            query_id=request.query_id,
            native=native,
        )
        if not created:
            loaded = self._load_completed(
                kind="discovery", intent=intent, lifecycle=lifecycle, native=native
            )
            if type(loaded.payload) is not DailyMedDiscoveryGroupV2:
                raise SnapshotIntegrityError("DailyMed V2 discovery payload type differs")
            return loaded.payload, loaded.record
        with self._new_connector() as connector:
            result = connector.discover_v2(**dict(native.query))
        completed = self._now()
        pages = () if result.value is None else result.value
        if result.value is None and result.pages_completed:
            # The connector intentionally withholds a value on a later-page
            # failure. Preserve only the independently replayable 200 pages;
            # coverage remains partial, so selection cannot follow.
            retained = []
            requested_pagesize = dict(native.query).get("pagesize")
            for number in range(1, result.pages_completed + 1):
                complete = tuple(
                    item
                    for item in result.raw_responses
                    if item.page_number == number and item.status_code == 200 and item.body_complete
                )
                if len(complete) != 1:
                    raise SnapshotIntegrityError("DailyMed V2 partial page raw is ambiguous")
                retained.append(
                    parse_discovery_page_v2(
                        complete[0].body,
                        expected_page=number,
                        expected_pagesize=(
                            int(requested_pagesize) if requested_pagesize is not None else None
                        ),
                    )
                )
            pages = tuple(retained)
        count = sum(len(page.records) for page in pages)
        outcome = self._outcome(
            request.query_id,
            count=count,
            pages=result.pages_completed,
            truncated=result.truncated,
            failed=result.failure is not None,
            has_raw=bool(result.raw_responses),
            failure_code=None if result.failure is None else result.failure.kind.value,
        )
        captured = self._capture(
            intent,
            lifecycle,
            outcome,
            result.raw_responses,
            requests_sent=result.request_count,
            pages_completed=result.pages_completed,
            completed=completed,
        )
        self._persist_source_rows(lifecycle, captured)
        summaries: list[DailyMedDiscoverySummaryV2] = []
        for page in pages:
            matching = tuple(
                (index, raw)
                for index, raw in enumerate(result.raw_responses)
                if raw.page_number == page.page
                and raw.status_code == 200
                and raw.body_complete
                and parse_discovery_page_v2(
                    raw.body,
                    expected_page=page.page,
                    expected_pagesize=page.pagesize,
                )
                == page
            )
            if len(matching) != 1:
                raise SnapshotIntegrityError("DailyMed V2 discovery page raw parent is ambiguous")
            member_ordinal, raw = matching[0]
            parent = self._raw_parent(captured.manifest, member_ordinal, kind="discovery_json")
            summaries.extend(
                project_discovery_summaries_v2(
                    raw.body,
                    parent=parent,
                    expected_page=page.page,
                    expected_pagesize=page.pagesize,
                    first_ordinal=len(summaries),
                )
            )
        group = DailyMedDiscoveryGroupV2(
            discovery_query_id=request.query_id,
            summaries=tuple(summaries),
            outcome=outcome,
            historical_pin=(
                request.selection_request.selection_mode is DailyMedSelectionMode.PINNED_VERSION
            ),
        )
        row = self._record_input(
            kind="discovery", intent=intent, manifest=captured.manifest, payload=group
        )
        self._records.save(row, group)
        self._repository.finalize_m1b_acquisition(replace(lifecycle, completed_at_utc=completed))
        loaded = self._load_completed(
            kind="discovery",
            intent=intent,
            lifecycle=replace(lifecycle, completed_at_utc=completed),
            native=native,
        )
        if loaded.payload != group:
            raise SnapshotIntegrityError("DailyMed V2 discovery durable replay differs")
        return group, row

    def _packaging(
        self, request: DailyMedPackagingRequestV2, ordinal: int
    ) -> tuple[DailyMedV2PackagingResult, DailyMedV2RecordInput]:
        query_id = derive_identity(
            "dailymed-packaging-query-v2",
            {
                "summary_id": request.summary_id,
                "setid": request.setid,
                "spl_version": request.expected_current_spl_version,
            },
        )
        native = build_dailymed_request(
            DailyMedOperation.PACKAGING,
            setid=request.setid,
            query={"pagesize": request.pagesize, "page": 1},
        )
        intent, lifecycle, created = self._begin(
            operation="packaging",
            ordinal=ordinal,
            query_id=query_id,
            native=native,
        )
        if not created:
            loaded = self._load_completed(
                kind="packaging", intent=intent, lifecycle=lifecycle, native=native
            )
            if type(loaded.payload) is not DailyMedV2PackagingResult:
                raise SnapshotIntegrityError("DailyMed V2 packaging payload type differs")
            return loaded.payload, loaded.record
        with self._new_connector() as connector:
            result = connector.packaging(
                request.setid,
                request.expected_current_spl_version,
                pagesize=request.pagesize,
            )
        completed = self._now()
        pages = () if result.value is None else result.value
        if result.value is None and result.pages_completed:
            retained = []
            for number in range(1, result.pages_completed + 1):
                complete = tuple(
                    item
                    for item in result.raw_responses
                    if item.page_number == number and item.status_code == 200 and item.body_complete
                )
                if len(complete) != 1:
                    raise SnapshotIntegrityError("DailyMed V2 partial packaging raw is ambiguous")
                retained.append(
                    parse_packaging_page(
                        complete[0].body,
                        expected_setid=request.setid,
                        expected_spl_version=request.expected_current_spl_version,
                        expected_page=number,
                    )
                )
            pages = tuple(retained)
        product_count = sum(len(page.products) for page in pages)
        outcome = self._outcome(
            query_id,
            count=product_count,
            pages=result.pages_completed,
            truncated=result.truncated,
            failed=result.failure is not None,
            has_raw=bool(result.raw_responses),
            failure_code=None if result.failure is None else result.failure.kind.value,
        )
        captured = self._capture(
            intent,
            lifecycle,
            outcome,
            result.raw_responses,
            requests_sent=result.request_count,
            pages_completed=result.pages_completed,
            completed=completed,
        )
        self._persist_source_rows(lifecycle, captured)
        execution: DailyMedPackagingExecutionV2 | None = None
        reason: DailyMedEnrichmentReason | None = None
        if result.failure is not None or result.value is None:
            reason = DailyMedEnrichmentReason.ENRICHMENT_UNAVAILABLE
        elif result.truncated or len(result.value) != 1:
            reason = DailyMedEnrichmentReason.ENRICHMENT_PAGINATION_UNSUPPORTED
        elif len(result.raw_responses) != 1:
            # The V2 closed candidate contract accepts one exact retained page.
            # Redirect/retry ancestry remains in the manifest, but cannot be
            # collapsed into a fabricated single response parent.
            reason = DailyMedEnrichmentReason.ENRICHMENT_UNAVAILABLE
        else:
            parent = self._raw_parent(captured.manifest, 0, kind="packaging_json")
            execution = DailyMedConnector.captured_packaging_v2(
                result,
                parent=parent,
                expected_setid=request.setid,
                expected_spl_version=request.expected_current_spl_version,
            )
        payload = DailyMedV2PackagingResult(
            summary_id=request.summary_id,
            discovery_query_id=request.discovery_query_id,
            packaging_query_id=query_id,
            setid=request.setid,
            expected_current_spl_version=request.expected_current_spl_version,
            source_outcome=outcome,
            execution=execution,
            reason=reason,
        )
        row = self._record_input(
            kind="packaging", intent=intent, manifest=captured.manifest, payload=payload
        )
        self._records.save(row, payload)
        self._repository.finalize_m1b_acquisition(replace(lifecycle, completed_at_utc=completed))
        loaded = self._load_completed(
            kind="packaging",
            intent=intent,
            lifecycle=replace(lifecycle, completed_at_utc=completed),
            native=native,
        )
        if loaded.payload != payload:
            raise SnapshotIntegrityError("DailyMed V2 packaging durable replay differs")
        return payload, row

    def _save_decision(
        self,
        decision: DailyMedSelectionDecisionV2,
        discovery_record: DailyMedV2RecordInput,
    ) -> DailyMedSelectionDecisionV2:
        if decision.discovery_query_id != discovery_record.query_id:
            raise SnapshotIntegrityError("DailyMed V2 decision belongs to another discovery")
        record = replace(
            discovery_record,
            record_kind="decision",
            payload_bytes=canonical_json(decision).encode("utf-8"),
        )
        loaded = self._records.save(record, decision)
        if type(loaded.payload) is not DailyMedSelectionDecisionV2:
            raise SnapshotIntegrityError("DailyMed V2 decision readback type differs")
        return loaded.payload

    def execute_current(self) -> DailyMedV2RunResult:
        """Execute all governed current-label groups through immutable stage barriers."""

        discovery_pairs: list[tuple[DailyMedDiscoveryGroupV2, DailyMedV2RecordInput]] = []
        for ordinal, selection in enumerate(self._request.dailymed_selection_requests):
            query_id = derive_identity(
                "dailymed-discovery-query",
                {
                    "run_id": self._run_id,
                    "scope_id": self._scope_id,
                    "request": selection,
                },
            )
            discovery_pairs.append(
                self._discovery(
                    DailyMedDiscoveryRequest(selection_request=selection, query_id=query_id),
                    ordinal,
                )
            )
        groups = tuple(item[0] for item in discovery_pairs)
        plans = plan_dailymed_enrichment_groups(groups)
        next_ordinal = len(groups)
        packaging_rows: list[DailyMedV2PackagingResult] = []
        packaging_by_summary: dict[str, DailyMedV2PackagingResult] = {}
        for plan in plans:
            for package_request in plan.requests:
                packaged, _row = self._packaging(package_request, next_ordinal)
                packaging_rows.append(packaged)
                packaging_by_summary[package_request.summary_id] = packaged
                next_ordinal += 1
        decisions: list[DailyMedSelectionDecisionV2] = []
        selected: list[DailyMedV2SelectedSplRecord] = []
        label_chunks: list[tuple[DailyMedV2EvidenceChunk, ...]] = []
        review: set[str] = set()
        selected_candidates: list[
            tuple[DailyMedSelectionDecisionV2, DailyMedEnrichedCandidateV2]
        ] = []
        for index, ((group, discovery_record), plan) in enumerate(
            zip(discovery_pairs, plans, strict=True)
        ):
            if plan.reason is not None:
                decision = select_enriched_candidates(groups, index, ())
            else:
                observed = tuple(packaging_by_summary[item.summary_id] for item in group.summaries)
                failed = next((item for item in observed if item.reason is not None), None)
                if failed is not None:
                    assert failed.reason is not None
                    decision = unavailable_enrichment_decision(group, reason=failed.reason)
                else:
                    candidates = tuple(
                        build_enriched_candidate(summary, packaged.execution)
                        for summary, packaged in zip(group.summaries, observed, strict=True)
                        if packaged.execution is not None
                    )
                    decision = select_enriched_candidates(groups, index, candidates)
                    if decision.status is DailyMedEnrichmentStatus.SELECTED:
                        selected_candidate = next(
                            item
                            for item in candidates
                            if item.candidate_id == decision.selected_candidate_id
                        )
                        selected_candidates.append((decision, selected_candidate))
            persisted_decision = self._save_decision(decision, discovery_record)
            decisions.append(persisted_decision)
            if persisted_decision.reason is not None:
                review.add(persisted_decision.reason.value)
        if next_ordinal + len(selected_candidates) > 8:
            raise SnapshotIntegrityError("DailyMed V2 selected fetches exceed reserved budget")
        for decision, candidate in selected_candidates:
            result, admitted = self._selected_spl(decision, candidate, next_ordinal)
            next_ordinal += 1
            if result.selected is not None:
                selected.append(result.selected)
            label_chunks.append(admitted)
            if result.review_reason is not None:
                review.add(result.review_reason)
        try:
            chunks = admit_dailymed_v2_task_chunks(tuple(label_chunks))
        except ValueError as error:
            if str(error) != "dailymed_v2_task_chunk_cap_exceeded":
                raise
            # Retain truthful completed retrieval while admitting no partial
            # subset to the terminal source task or registry.
            review.add("task_chunk_cap_exceeded")
            chunks = ()
        return DailyMedV2RunResult(
            groups=groups,
            packaging=tuple(packaging_rows),
            decisions=tuple(decisions),
            selected_spl=tuple(selected),
            evidence_chunks=chunks,
            review_reason_codes=tuple(sorted(review)),
        )

    def _selected_spl(
        self,
        decision: DailyMedSelectionDecisionV2,
        candidate: DailyMedEnrichedCandidateV2,
        ordinal: int,
    ) -> tuple[DailyMedV2SelectedSplResult, tuple[DailyMedV2EvidenceChunk, ...]]:
        if (
            decision.status is not DailyMedEnrichmentStatus.SELECTED
            or decision.selected_candidate_id != candidate.candidate_id
        ):
            raise ValueError("DailyMed V2 current SPL requires one exact selected candidate")
        setid = candidate.summary.setid
        version = candidate.summary.current_spl_version
        native = build_dailymed_request(
            DailyMedOperation.CURRENT_SPL,
            setid=setid,
            spl_version=version,
        )
        intent, lifecycle, created = self._begin(
            operation="selected_spl",
            ordinal=ordinal,
            query_id=decision.discovery_query_id,
            native=native,
            selected_setid=setid,
            selected_spl_version=version,
        )
        if not created:
            loaded = self._load_completed(
                kind="selected_spl", intent=intent, lifecycle=lifecycle, native=native
            )
            if type(loaded.payload) is not DailyMedV2SelectedSplResult:
                raise SnapshotIntegrityError("DailyMed V2 current SPL replay type differs")
            loaded_chunks = self._reload_selected_chunks(loaded.payload, loaded.record)
            return loaded.payload, loaded_chunks
        with self._new_connector() as connector:
            result = connector.fetch_spl(setid, version, historical=False)
        if result.from_cache:
            raise SnapshotIntegrityError("DailyMed V2 current SPL cannot use in-memory cache")
        completed = self._now()
        valid = result.value is not None and result.failure is None
        outcome = self._outcome(
            intent.query_id,
            count=1 if valid else 0,
            pages=result.pages_completed,
            truncated=result.truncated,
            failed=not valid,
            has_raw=bool(result.raw_responses),
            failure_code=None if result.failure is None else result.failure.kind.value,
        )
        stable: bytes | None = None
        if valid:
            terminal = tuple(
                item
                for item in result.raw_responses
                if item.body_complete and item.status_code == 200
            )
            if len(terminal) != 1:
                raise SnapshotIntegrityError("DailyMed V2 selected SPL lacks sole current raw")
            stable = terminal[0].body
        captured = self._capture(
            intent,
            lifecycle,
            outcome,
            result.raw_responses,
            requests_sent=result.request_count,
            pages_completed=result.pages_completed,
            completed=completed,
            stable_spl_bytes=stable,
        )
        self._persist_source_rows(lifecycle, captured)
        selected: DailyMedV2SelectedSplRecord | None = None
        chunks: tuple[DailyMedV2EvidenceChunk, ...] = ()
        review_reason: (
            Literal["source_unavailable", "current_version_drift", "chunk_cap_exceeded"] | None
        ) = None
        if not valid:
            review_reason = (
                "current_version_drift"
                if result.failure is not None and result.failure.kind.value == "identity_drift"
                else "source_unavailable"
            )
        else:
            assert stable is not None
            native_document = parse_source_native_spl_document(
                stable, expected_setid=setid, expected_spl_version=version
            )
            stable_hash = sha256_digest(stable)
            source_version = derive_identity(
                "dailymed-v2-label-version",
                {"setid": setid, "spl_version": version, "stable_spl_hash": stable_hash},
            )
            try:
                chunks = build_dailymed_v2_chunks(
                    run_id=self._run_id,
                    snapshot_id=captured.manifest.snapshot_id,
                    source_version=source_version,
                    sections=native_document.sections,
                )
            except ValueError as error:
                if str(error) != "dailymed_v2_label_chunk_cap_exceeded":
                    raise
                review_reason = "chunk_cap_exceeded"
                chunks = ()
            selected = DailyMedV2SelectedSplRecord(
                decision=decision,
                candidate=candidate,
                run_id=self._run_id,
                attempt_id=self._attempt_id,
                discovery_query_id=decision.discovery_query_id,
                fetch_query_id=intent.query_id,
                fetch_snapshot_id=captured.manifest.snapshot_id,
                fetch_manifest_id=captured.manifest.manifest_id,
                stable_spl_hash=stable_hash,
                section_refs=tuple(
                    DailyMedV2SectionRef.from_section(item) for item in native_document.sections
                ),
                evidence_chunk_ids=tuple(item.evidence_id for item in chunks),
            )
        payload = DailyMedV2SelectedSplResult(
            source_outcome=outcome,
            selected=selected,
            review_reason=review_reason,
        )
        row = self._record_input(
            kind="selected_spl", intent=intent, manifest=captured.manifest, payload=payload
        )
        self._records.save(row, payload)
        for chunk in chunks:
            self._records.save(
                self._record_input(
                    kind="chunk",
                    intent=intent,
                    manifest=captured.manifest,
                    payload=chunk,
                    item_ordinal=chunk.chunk_ordinal,
                ),
                chunk,
            )
        self._repository.finalize_m1b_acquisition(replace(lifecycle, completed_at_utc=completed))
        if chunks:
            from .dailymed_v2_provenance import DailyMedV2ProvenanceStore

            proofs = DailyMedV2ProvenanceStore(
                snapshots=self._snapshots,
                repository=self._repository,
                records=self._records,
            )
            for chunk in chunks:
                proofs.publish(chunk)
        loaded = self._load_completed(
            kind="selected_spl",
            intent=intent,
            lifecycle=replace(lifecycle, completed_at_utc=completed),
            native=native,
        )
        if loaded.payload != payload:
            raise SnapshotIntegrityError("DailyMed V2 selected SPL durable replay differs")
        return payload, self._reload_selected_chunks(payload, row)

    def _reload_selected_chunks(
        self,
        payload: DailyMedV2SelectedSplResult,
        record: DailyMedV2RecordInput,
    ) -> tuple[DailyMedV2EvidenceChunk, ...]:
        selected = payload.selected
        if selected is None:
            return ()
        manifest = replay_dailymed_v2(
            self._snapshots,
            manifest_id=record.manifest_id,
            expected_operation="selected_spl",
            expected_run_id=record.run_id,
            expected_acquisition_id=record.acquisition_id,
            expected_intent_id=record.acquisition_intent_id,
            expected_query_id=record.query_id,
            expected_request_identity=self._load_intent(
                record.acquisition_intent_id
            ).request_identity,
        )
        stable = tuple(item for item in manifest.members if item.kind == "dailymed_spl_xml")
        if len(stable) != 1 or stable[0].content_hash != selected.stable_spl_hash:
            raise SnapshotIntegrityError("DailyMed V2 stable SPL member differs")
        target = self._snapshots.root.joinpath(*stable[0].relative_path.split("/"))
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        with target.open("rb") as handle:
            raw = handle.read(5_242_881)
        if len(raw) != stable[0].byte_size or sha256_digest(raw) != selected.stable_spl_hash:
            raise SnapshotIntegrityError("DailyMed V2 stable SPL bytes differ")
        parsed = parse_source_native_spl_document(
            raw,
            expected_setid=selected.candidate.summary.setid,
            expected_spl_version=selected.candidate.summary.current_spl_version,
        )
        if selected.section_refs != tuple(
            DailyMedV2SectionRef.from_section(item) for item in parsed.sections
        ):
            raise SnapshotIntegrityError("DailyMed V2 source-native section refs differ")
        if payload.review_reason == "chunk_cap_exceeded":
            try:
                build_dailymed_v2_chunks(
                    run_id=self._run_id,
                    snapshot_id=record.snapshot_id,
                    source_version=derive_identity(
                        "dailymed-v2-label-version",
                        {
                            "setid": selected.candidate.summary.setid,
                            "spl_version": selected.candidate.summary.current_spl_version,
                            "stable_spl_hash": selected.stable_spl_hash,
                        },
                    ),
                    sections=parsed.sections,
                )
            except ValueError as error:
                if str(error) == "dailymed_v2_label_chunk_cap_exceeded":
                    return ()
                raise
            raise SnapshotIntegrityError("DailyMed V2 chunk-cap review is unsupported")
        expected = build_dailymed_v2_chunks(
            run_id=self._run_id,
            snapshot_id=record.snapshot_id,
            source_version=derive_identity(
                "dailymed-v2-label-version",
                {
                    "setid": selected.candidate.summary.setid,
                    "spl_version": selected.candidate.summary.current_spl_version,
                    "stable_spl_hash": selected.stable_spl_hash,
                },
            ),
            sections=parsed.sections,
        )
        if tuple(item.evidence_id for item in expected) != selected.evidence_chunk_ids:
            raise SnapshotIntegrityError("DailyMed V2 selected evidence membership differs")
        loaded_chunks = []
        from .dailymed_v2_provenance import DailyMedV2ProvenanceStore

        proofs = DailyMedV2ProvenanceStore(
            snapshots=self._snapshots,
            repository=self._repository,
            records=self._records,
        )
        for chunk in expected:
            stored = self._records.load_slot(
                run_id=self._run_id,
                attempt_id=self._attempt_id,
                record_kind="chunk",
                query_id=record.query_id,
                item_ordinal=chunk.chunk_ordinal,
            )
            if stored is None or stored.payload != chunk:
                raise SnapshotIntegrityError("DailyMed V2 evidence chunk is missing or foreign")
            proof = proofs.load_verified_provenance(
                run_id=chunk.run_id,
                evidence_id=chunk.evidence_id,
                source=SourceType.DAILYMED,
                source_record_id=chunk.source_record_id,
                source_version=chunk.source_version,
                snapshot_id=chunk.snapshot_id,
                content_hash=chunk.chunk_hash,
            )
            if proof is None:
                # The acquisition is terminal and its immutable source graph was
                # replayed above. Resume only the missing local proof write.
                proofs.publish(chunk)
            loaded_chunks.append(chunk)
        return tuple(loaded_chunks)
