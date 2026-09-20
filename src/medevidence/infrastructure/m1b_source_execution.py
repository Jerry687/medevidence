"""Bounded source execution bridges with durable START-before-I/O semantics."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Protocol, final

import httpx

from medevidence.connectors.dailymed import DailyMedRequest
from medevidence.connectors.faers import FaersConnector, FaersConnectorConfig
from medevidence.connectors.faers.client import (
    FaersConnectorResult,
    recognized_empty_count_response,
)
from medevidence.connectors.faers.parsing import FaersParseError, parse_count_page
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    FaersAggregateResult,
    M1BResearchRequestV1,
    ResearchScope,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.reports import AcquisitionOutcomeRef
from medevidence.infrastructure.m1b_evidence_provenance import (
    VerifiedM1BEvidenceProvenanceStore,
)
from medevidence.ingestion import (
    RawResponseObservation,
    capture_faers_snapshot,
    replay_faers_snapshot,
)
from medevidence.ingestion.artifacts import (
    MAX_MANIFEST_BYTES,
    CapturedFaersSnapshot,
    FaersSnapshotManifest,
)
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.orchestration.contracts import (
    MAX_SOURCE_TASK_ATTEMPTS,
    source_task_attempt,
    source_task_id,
)
from medevidence.persistence.repositories import (
    M1BAcquisitionLifecycle,
    M1BRunLifecycle,
    PersistenceRepository,
)
from medevidence.tools.contracts import (
    DailyMedDiscoveryRequest,
    FaersAggregateExecution,
    PersistedFaersAggregate,
)
from medevidence.tools.faers import (
    FaersAggregateExecutionProjection,
    FaersAggregateProvenanceProjection,
    FaersBucketEvidenceProjection,
)
from medevidence.tools.report_validation import EvidenceInput
from medevidence.tools.source_evidence_material import (
    MAX_SOURCE_EXECUTION_INTENT_BYTES,
    FaersSourceExecutionIntentV1,
    canonical_faers_bucket_evidence,
    faers_source_execution_intent_id,
)

_CODE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_RUN_UUID = re.compile(
    r"^run:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$"
)


class M1BSourceExecutionUnavailable(RuntimeError):
    """Stable fail-closed source execution state."""


class DailyMedNativeDiscoveryRequestPort(Protocol):
    """Map governed local input to one exact validated DailyMed request."""

    def resolve(self, request: DailyMedDiscoveryRequest) -> DailyMedRequest: ...


class DailyMedCandidateEnrichmentPort(Protocol):
    """Future retained-source authority for complete DailyMed candidates."""

    def available(self) -> bool: ...


@final
class DailyMedSourceExecutionBridge:
    """Reject execution until retained candidate enrichment is configured."""

    def __init__(
        self,
        *,
        native_requests: DailyMedNativeDiscoveryRequestPort,
        candidate_enrichment: DailyMedCandidateEnrichmentPort | None,
    ) -> None:
        del native_requests
        if candidate_enrichment is None or candidate_enrichment.available() is not True:
            raise M1BSourceExecutionUnavailable("dailymed_candidate_enrichment_unavailable")
        raise M1BSourceExecutionUnavailable("dailymed_execution_bridge_not_implemented")


def _exact_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source execution clock must return timezone-aware UTC")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("source execution clock must return UTC")
    return value


def _intent_relative_path(run_id: str, intent_id: str) -> str:
    run = _RUN_UUID.fullmatch(run_id)
    digest = intent_id.removeprefix("acquisition-intent:sha256:")
    if run is None or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SnapshotIntegrityError("source execution intent identity is invalid")
    return f"journal/{run.group(1)}/source-execution/faers/{digest}/intent.json"


def _read_exact_intent(store: SnapshotStore, relative: str) -> bytes | None:
    target = store.root.joinpath(*relative.split("/"))
    SnapshotStore._require_safe_path(store, target, allow_missing_leaf=True)
    if not target.exists():
        return None
    if not target.is_file() or not 0 < target.stat().st_size <= MAX_SOURCE_EXECUTION_INTENT_BYTES:
        raise SnapshotIntegrityError("source execution intent file is invalid")
    size = target.stat().st_size
    with target.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_EXECUTION_INTENT_BYTES + 1)
    SnapshotStore._require_safe_path(store, target, allow_missing_leaf=False)
    if len(raw) > MAX_SOURCE_EXECUTION_INTENT_BYTES or len(raw) != size:
        raise SnapshotIntegrityError("source execution intent changed during read")
    return raw


@final
class FaersSourceExecutionBridge:
    """Execute, persist, and replay one governed FAERS aggregate per request."""

    __slots__ = (
        "_attempt_id",
        "_clock",
        "_code_revision",
        "_repository",
        "_request",
        "_run_id",
        "_scope_id",
        "_store",
        "_task_id",
        "_transport_factory",
    )
    _attempt_id: str
    _clock: Callable[[], datetime]
    _code_revision: str
    _repository: PersistenceRepository
    _request: M1BResearchRequestV1
    _run_id: str
    _scope_id: str
    _store: SnapshotStore
    _task_id: str
    _transport_factory: Callable[[], httpx.BaseTransport]

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
        transport_factory: Callable[[], httpx.BaseTransport],
        store: SnapshotStore,
        repository: PersistenceRepository,
    ) -> None:
        if (
            type(scope) is not ResearchScope
            or type(request) is not M1BResearchRequestV1
            or type(run_id) is not str
            or _RUN_UUID.fullmatch(run_id) is None
        ):
            raise ValueError("FAERS source bridge requires exact governed context")
        exact_scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        exact_request = M1BResearchRequestV1.model_validate(
            request.model_dump(mode="python"),
            strict=True,
        )
        if exact_request.scope != exact_scope or exact_request.scope.scope_id != scope.scope_id:
            raise ValueError("FAERS source bridge request/scope binding differs")
        if SourceType.FAERS not in exact_request.requested_sources:
            raise ValueError("FAERS source bridge requires FAERS in the governed request")
        if (
            exact_scope.query_bounds.max_query_characters < 512
            or exact_scope.query_bounds.max_pages < 5
            or exact_scope.query_bounds.max_total_seconds < 30
            or exact_scope.result_bounds.max_records < 100
            or exact_scope.result_bounds.max_payload_bytes < 5_242_880
        ):
            raise M1BSourceExecutionUnavailable("faers_scope_budget_below_fixed_profile")
        if task_id != source_task_id(run_id, SourceType.FAERS):
            raise ValueError("FAERS source bridge task identity differs")
        if type(attempt_id) is not str or attempt_id not in {
            source_task_attempt(task_id, number).attempt_id
            for number in range(1, MAX_SOURCE_TASK_ATTEMPTS + 1)
        }:
            raise ValueError("FAERS source bridge attempt identity is invalid")
        if _CODE_REVISION.fullmatch(code_revision) is None:
            raise ValueError("FAERS source bridge code revision is invalid")
        if type(store) is not SnapshotStore or type(repository) is not PersistenceRepository:
            raise TypeError("FAERS source bridge requires exact persistence authorities")
        object.__setattr__(self, "_run_id", run_id)
        object.__setattr__(self, "_scope_id", exact_scope.scope_id)
        object.__setattr__(self, "_request", exact_request)
        object.__setattr__(self, "_task_id", task_id)
        object.__setattr__(self, "_attempt_id", attempt_id)
        object.__setattr__(self, "_clock", clock)
        object.__setattr__(self, "_code_revision", code_revision)
        object.__setattr__(self, "_transport_factory", transport_factory)
        object.__setattr__(self, "_store", store)
        object.__setattr__(self, "_repository", repository)

    def execute(self, query: FaersAggregateQueryV1) -> FaersAggregateExecution:
        """Persist START before HTTP and return only a fully replayed execution."""

        exact_query = FaersAggregateQueryV1.model_validate(
            query.model_dump(mode="python"), strict=True
        )
        requests = self._request.faers_query_requests
        matching = tuple(
            item for item in requests if FaersAggregateQueryV1.create(item) == exact_query
        )
        if len(matching) != 1:
            raise ValueError("FAERS query is outside the governed request")
        ordinal = requests.index(matching[0])
        request_hash = sha256_digest(canonical_json(exact_query))
        intent_id = faers_source_execution_intent_id(
            run_id=self._run_id,
            scope_id=self._scope_id,
            task_id=self._task_id,
            attempt_id=self._attempt_id,
            acquisition_ordinal=ordinal,
            query_id=exact_query.query_id,
            request_hash=request_hash,
            code_revision=self._code_revision,
        )
        acquisition_id = derive_identity(
            "acquisition",
            {"run_id": self._run_id, "source": "faers", "intent_id": intent_id},
        )
        started = _exact_utc(self._clock)
        existing_run = self._repository.get_m1b_run_lifecycle(self._run_id)
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
            raise ValueError("FAERS source bridge stored run identity differs")
        elif (
            existing_run.status != "running"
            and self._repository.get_m1b_acquisition_lifecycle(acquisition_id) is None
        ):
            raise M1BSourceExecutionUnavailable("faers_run_already_terminal")
        lifecycle = M1BAcquisitionLifecycle(
            acquisition_intent_id=intent_id,
            acquisition_ordinal=ordinal,
            attempt_id=self._attempt_id,
            run_id=self._run_id,
            acquisition_id=acquisition_id,
            source="faers",
            operation="search",
            request_identity=exact_query.query_id,
            query_id=exact_query.query_id,
            execution_profile_id=exact_query.execution_profile_id,
            started_at_utc=started,
            completed_at_utc=None,
            schema_version="m1b.acquisition.v1",
        )
        stored, created = self._repository.begin_m1b_acquisition(lifecycle)
        keys = {
            "run_id": self._run_id,
            "task_id": self._task_id,
            "attempt_id": self._attempt_id,
            "query_id": exact_query.query_id,
            "acquisition_intent_id": intent_id,
        }
        if not created:
            self._load_intent(intent_id, exact_query)
            if stored.completed_at_utc is None:
                raise M1BSourceExecutionUnavailable("faers_started_state_unknown")
            return self.persist(self._load_execution(keys)).execution
        intent = FaersSourceExecutionIntentV1(
            acquisition_intent_id=intent_id,
            run_id=self._run_id,
            scope_id=self._scope_id,
            task_id=self._task_id,
            attempt_id=self._attempt_id,
            acquisition_id=acquisition_id,
            acquisition_ordinal=ordinal,
            query_id=exact_query.query_id,
            request_hash=request_hash,
            query=exact_query,
            created_at_utc=started,
            code_revision=self._code_revision,
        )
        self._publish_intent(intent)
        self._load_intent(intent_id, exact_query)
        transport = self._transport_factory()
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("FAERS transport factory returned an invalid transport")
        connector = FaersConnector(
            transport,
            FaersConnectorConfig(),
            utc_now=self._clock,
        )
        try:
            connected = connector.aggregate(exact_query)
        finally:
            connector.close()
        completed = _exact_utc(self._clock)
        execution = self._persist_connector_result(
            query=exact_query,
            lifecycle=lifecycle,
            completed=completed,
            connected=connected,
            keys=keys,
        )
        return self.persist(execution).execution

    def persist(self, execution: FaersAggregateExecution) -> PersistedFaersAggregate:
        """Verify the exact durable replay; execution already persisted before return."""

        exact = FaersAggregateExecution.model_validate(
            execution.model_dump(mode="python"), strict=True
        )
        ref = exact.acquisition_outcome_ref
        lifecycle = self._repository.get_m1b_acquisition_lifecycle(ref.acquisition_id)
        if lifecycle is None or lifecycle.completed_at_utc is None:
            raise SnapshotIntegrityError("FAERS persisted acquisition is incomplete")
        intent = self._load_intent(ref.acquisition_intent_id, exact.result.query)
        if (
            intent.acquisition_id != ref.acquisition_id
            or intent.acquisition_ordinal != ref.acquisition_ordinal
            or lifecycle.acquisition_intent_id != ref.acquisition_intent_id
            or lifecycle.attempt_id != self._attempt_id
            or lifecycle.run_id != self._run_id
            or lifecycle.acquisition_ordinal != intent.acquisition_ordinal
            or lifecycle.query_id != intent.query_id
            or lifecycle.request_identity != intent.query_id
            or lifecycle.execution_profile_id != exact.result.query.execution_profile_id
            or lifecycle.started_at_utc != intent.created_at_utc
        ):
            raise SnapshotIntegrityError("FAERS persisted START binding differs")
        loaded = self._load_execution(
            {
                "run_id": ref.run_id,
                "task_id": self._task_id,
                "attempt_id": self._attempt_id,
                "query_id": ref.query_id,
                "acquisition_intent_id": ref.acquisition_intent_id,
            }
        )
        if loaded != exact:
            raise SnapshotIntegrityError("FAERS persisted execution differs")
        self._verified_bucket_evidence(loaded)
        return PersistedFaersAggregate(execution=loaded)

    def load_aggregate(
        self, *, execution: FaersAggregateExecution
    ) -> FaersAggregateProvenanceProjection:
        """Return canonical bucket IDs only after durable execution replay."""

        persisted = self.persist(execution).execution
        evidence = self._verified_bucket_evidence(persisted)
        return FaersAggregateProvenanceProjection(
            run_id=self._run_id,
            scope_id=self._scope_id,
            task_id=self._task_id,
            attempt_id=self._attempt_id,
            query_id=persisted.result.query.query_id,
            snapshot_id=persisted.result.snapshot_id,
            manifest_id=persisted.result.manifest_id,
            bucket_evidence=tuple(
                FaersBucketEvidenceProjection(
                    bucket_ordinal=index,
                    evidence_id=item.evidence_id,
                    content_hash=item.content_hash,
                    locator_ref=item.locators[0],
                )
                for index, item in enumerate(evidence)
            ),
        )

    def _verified_bucket_evidence(
        self, persisted: FaersAggregateExecution
    ) -> tuple[EvidenceInput, ...]:
        evidence = tuple(
            canonical_faers_bucket_evidence(persisted, bucket.bucket_ordinal)
            for bucket in persisted.result.buckets
        )
        digest = persisted.result.manifest_id.removeprefix("sha256:")
        manifest_path = f"faers/manifests/sha256/{digest[:2]}/{digest}.json"
        manifest_raw = self._read_content_addressed(
            manifest_path, persisted.result.manifest_id, MAX_MANIFEST_BYTES
        )
        parsed_manifest = FaersSnapshotManifest.from_json_bytes(manifest_raw)
        manifest = replay_faers_snapshot(
            manifest_raw,
            self._store,
            expected_manifest_id=persisted.result.manifest_id,
            expected_query=persisted.result.query,
            expected_members=parsed_manifest.members,
            recognized_empty_response=recognized_empty_count_response,
        )
        rows = self._repository.load_m1b_faers_terminal_rows(
            run_id=self._run_id,
            acquisition_id=persisted.acquisition_outcome_ref.acquisition_id,
            query_id=persisted.result.query.query_id,
            snapshot_id=persisted.result.snapshot_id,
            source_outcome_id=persisted.acquisition_outcome_ref.source_outcome_id,
        )
        if rows is None:
            raise SnapshotIntegrityError("FAERS terminal PostgreSQL graph is missing")
        acquisition_row = rows["acquisition"]
        snapshot_row = rows["snapshot"]
        outcome_row = rows["outcome"]
        query_row = rows["query"]
        member_rows = rows["members"]
        bucket_rows = rows["buckets"]
        if (
            not isinstance(acquisition_row, dict)
            or not isinstance(snapshot_row, dict)
            or not isinstance(outcome_row, dict)
            or not isinstance(query_row, dict)
            or not isinstance(member_rows, tuple)
            or not isinstance(bucket_rows, tuple)
            or acquisition_row.get("acquisition_intent_id") != manifest.acquisition_intent_id
            or acquisition_row.get("attempt_id") != self._attempt_id
            or acquisition_row.get("acquisition_ordinal") != manifest.acquisition_ordinal
            or acquisition_row.get("completed_at_utc") != manifest.completed_at_utc
            or snapshot_row.get("manifest_artifact_id") != manifest.manifest_id
            or snapshot_row.get("retrieved_at_utc") != manifest.retrieved_at_utc
            or query_row.get("retrieved_at_utc") != manifest.retrieved_at_utc
            or query_row.get("execution_profile_id") != manifest.query.execution_profile_id
            or query_row.get("ast_schema_version") != manifest.query.ast_schema_version
            or query_row.get("serializer_version") != manifest.query.serializer_version
            or outcome_row.get("execution_status") != manifest.source_outcome.execution_status.value
            or outcome_row.get("coverage_status") != manifest.source_outcome.coverage_status.value
            or outcome_row.get("result_status") != manifest.source_outcome.result_status.value
            or outcome_row.get("valid_result_count") != len(manifest.buckets)
            or outcome_row.get("pages_completed") != manifest.source_outcome.pages_completed
            or len(member_rows) != len(manifest.members)
            or len(bucket_rows) != len(manifest.buckets)
        ):
            raise SnapshotIntegrityError("FAERS terminal PostgreSQL graph differs")
        expected_query_row = PersistenceRepository._faers_query_row(
            run_id=self._run_id,
            acquisition_id=persisted.acquisition_outcome_ref.acquisition_id,
            result=persisted.result,
        )
        if (
            any(
                query_row.get(name) != value
                for name, value in expected_query_row.items()
                if name != "role_predicate_json"
            )
            or query_row.get("role_predicate_json") is not None
        ):
            raise SnapshotIntegrityError("FAERS PostgreSQL query differs")
        expected_outcome = persisted.result.source_outcome
        expected_bounds = expected_outcome.configured_bounds
        outcome_fields = {
            "source_outcome_id": persisted.acquisition_outcome_ref.source_outcome_id,
            "snapshot_id": manifest.snapshot_id,
            "run_id": self._run_id,
            "query_id": manifest.query.query_id,
            "acquisition_id": manifest.acquisition_id,
            "source": "faers",
            "acquisition_intent_id": manifest.acquisition_intent_id,
            "acquisition_ordinal": manifest.acquisition_ordinal,
            "operation": "search",
            "execution_status": expected_outcome.execution_status.value,
            "coverage_status": expected_outcome.coverage_status.value,
            "result_status": expected_outcome.result_status.value,
            "max_query_characters": expected_bounds.max_query_characters,
            "max_pages": expected_bounds.max_pages,
            "max_records": expected_bounds.max_records,
            "max_payload_bytes": expected_bounds.max_payload_bytes,
            "max_total_seconds": expected_bounds.max_total_seconds,
            "valid_result_count": expected_outcome.valid_result_count,
            "pages_completed": expected_outcome.pages_completed,
            "truncated": expected_outcome.truncated,
            "failure_id": expected_outcome.failure_id,
            "warning_codes": list(expected_outcome.warning_codes),
            "schema_version": "1.0",
        }
        if any(outcome_row.get(name) != value for name, value in outcome_fields.items()):
            raise SnapshotIntegrityError("FAERS PostgreSQL outcome differs")
        for expected_member, row in zip(manifest.members, member_rows, strict=True):
            if not isinstance(row, dict) or (
                row.get("ordinal") != expected_member.ordinal
                or row.get("link_id") != expected_member.link_id
                or row.get("artifact_id") != expected_member.artifact_id
                or row.get("content_hash") != expected_member.content_hash
                or row.get("http_status") != expected_member.http_status
                or row.get("body_complete") != expected_member.body_complete
                or row.get("termination_reason") != expected_member.termination_reason
                or row.get("observed_at_utc") != expected_member.observed_at_utc
            ):
                raise SnapshotIntegrityError("FAERS terminal PostgreSQL member differs")
        for expected_bucket, row in zip(manifest.buckets, bucket_rows, strict=True):
            if not isinstance(row, dict) or (
                row.get("bucket_ordinal") != expected_bucket.bucket_ordinal
                or row.get("reaction_pt") != expected_bucket.reaction_pt
                or row.get("report_count") != expected_bucket.report_count
                or row.get("statistical_unit") != expected_bucket.statistical_unit
                or row.get("identity_stratum") != expected_bucket.identity_stratum
                or row.get("role_policy") != expected_bucket.role_policy
            ):
                raise SnapshotIntegrityError("FAERS terminal PostgreSQL bucket differs")
        if (
            manifest.run_id != self._run_id
            or manifest.acquisition_id != persisted.acquisition_outcome_ref.acquisition_id
            or manifest.acquisition_intent_id
            != persisted.acquisition_outcome_ref.acquisition_intent_id
            or manifest.snapshot_id != persisted.result.snapshot_id
            or manifest.source_outcome != persisted.result.source_outcome
            or manifest.buckets != persisted.result.buckets
            or manifest.retrieved_at_utc != persisted.result.retrieved_at_utc
            or manifest.provider_as_of_utc != persisted.result.provider_as_of_utc
        ):
            raise SnapshotIntegrityError("FAERS source manifest differs from execution")
        complete = tuple(
            member
            for member in manifest.members
            if member.body_complete and member.termination_reason == "complete_response"
        )
        if persisted.result.source_outcome.coverage_status is CoverageStatus.COMPLETE:
            if len(complete) != 1:
                raise SnapshotIntegrityError("complete FAERS source has no sole raw response")
            terminal = complete[0]
            raw = self._read_parent(
                terminal.relative_path,
                terminal.byte_size,
                terminal.content_hash,
                5_242_880,
            )
            if terminal.http_status == 404:
                if (
                    persisted.result.source_outcome.result_status is not ResultStatus.NO_MATCH
                    or persisted.result.buckets
                    or not recognized_empty_count_response(terminal.http_status, raw)
                ):
                    raise SnapshotIntegrityError("FAERS empty 404 replay differs")
            else:
                try:
                    page = parse_count_page(raw)
                except FaersParseError as error:
                    raise SnapshotIntegrityError("FAERS raw count replay failed") from error
                if tuple((row.reaction_pt, row.report_count) for row in page.buckets) != tuple(
                    (row.reaction_pt, row.report_count) for row in persisted.result.buckets
                ):
                    raise SnapshotIntegrityError("FAERS raw count differs from execution")
        elif persisted.result.buckets:
            raise SnapshotIntegrityError("partial FAERS count exposed unsupported buckets")
        for bucket, item in zip(persisted.result.buckets, evidence, strict=True):
            binding = self._repository.get_faers_evidence_binding(
                run_id=self._run_id,
                acquisition_id=persisted.acquisition_outcome_ref.acquisition_id,
                query_id=persisted.result.query.query_id,
                source_outcome_id=persisted.acquisition_outcome_ref.source_outcome_id,
                snapshot_id=persisted.result.snapshot_id,
                bucket_ordinal=bucket.bucket_ordinal,
            )
            if binding is None or (
                binding.reaction_pt != bucket.reaction_pt
                or binding.report_count != bucket.report_count
                or binding.statistical_unit != bucket.statistical_unit
                or binding.identity_stratum != bucket.identity_stratum
                or binding.role_policy != bucket.role_policy
                or item.content_hash
                != sha256_digest(
                    canonical_json(
                        {
                            "query_id": binding.query_id,
                            "bucket_ordinal": binding.bucket_ordinal,
                            "reaction_pt": binding.reaction_pt,
                            "report_count": binding.report_count,
                            "statistical_unit": binding.statistical_unit,
                            "identity_stratum": binding.identity_stratum,
                            "role_policy": binding.role_policy,
                        }
                    )
                )
            ):
                raise SnapshotIntegrityError("FAERS persisted bucket provenance differs")
            if (
                binding.manifest.content_hash != persisted.result.manifest_id
                or binding.manifest.relative_path != manifest_path
                or len(complete) != 1
                or any(
                    (
                        binding.raw.artifact_id,
                        binding.raw.content_hash,
                        binding.raw.relative_path,
                        binding.raw.byte_size,
                        binding.raw.artifact_kind,
                    )
                    != (
                        member.artifact_id,
                        member.content_hash,
                        member.relative_path,
                        member.byte_size,
                        member.artifact_kind,
                    )
                    for member in complete
                )
            ):
                raise SnapshotIntegrityError("FAERS source manifest membership differs")
        return evidence

    def _read_content_addressed(self, relative: str, expected_hash: str, cap: int) -> bytes:
        target = self._store.root.joinpath(*relative.split("/"))
        SnapshotStore._require_safe_path(self._store, target, allow_missing_leaf=False)
        if not target.is_file() or not 0 < target.stat().st_size <= cap:
            raise SnapshotIntegrityError("FAERS source manifest is missing or oversized")
        with target.open("rb") as handle:
            raw = handle.read(cap + 1)
        SnapshotStore._require_safe_path(self._store, target, allow_missing_leaf=False)
        if len(raw) > cap or sha256_digest(raw) != expected_hash:
            raise SnapshotIntegrityError("FAERS source manifest bytes differ")
        return raw

    def _read_parent(
        self, relative: str, expected_size: int, expected_hash: str, cap: int
    ) -> bytes:
        target = self._store.root.joinpath(*relative.split("/"))
        SnapshotStore._require_safe_path(self._store, target, allow_missing_leaf=False)
        if not target.is_file() or not 0 < target.stat().st_size <= cap:
            raise SnapshotIntegrityError("FAERS source parent is missing or oversized")
        with target.open("rb") as handle:
            raw = handle.read(cap + 1)
        SnapshotStore._require_safe_path(self._store, target, allow_missing_leaf=False)
        if len(raw) > cap or len(raw) != expected_size or sha256_digest(raw) != expected_hash:
            raise SnapshotIntegrityError("FAERS source parent bytes differ")
        return raw

    def _persist_connector_result(
        self,
        *,
        query: FaersAggregateQueryV1,
        lifecycle: M1BAcquisitionLifecycle,
        completed: datetime,
        connected: FaersConnectorResult,
        keys: dict[str, str],
    ) -> FaersAggregateExecution:
        if type(connected) is not FaersConnectorResult:
            raise TypeError("FAERS connector returned a noncanonical result")
        if connected.value is not None:
            page = connected.value
            buckets = tuple(
                FaersAggregateBucketV1.model_validate(
                    {
                        "query_id": query.query_id,
                        "bucket_ordinal": index,
                        "reaction_pt": item.reaction_pt,
                        "report_count": item.report_count,
                        "identity_stratum": query.identity_stratum,
                    },
                    strict=True,
                )
                for index, item in enumerate(page.buckets)
            )
            coverage = CoverageStatus.PARTIAL if connected.truncated else CoverageStatus.COMPLETE
            result_status = (
                ResultStatus.MATCHES
                if buckets
                else (ResultStatus.INDETERMINATE if connected.truncated else ResultStatus.NO_MATCH)
            )
            execution_status = ExecutionStatus.SUCCEEDED
            failure_id = None
            provider_as_of = page.provider_as_of_utc
        else:
            buckets = ()
            coverage = (
                CoverageStatus.PARTIAL if connected.raw_responses else CoverageStatus.UNAVAILABLE
            )
            result_status = ResultStatus.INDETERMINATE
            execution_status = ExecutionStatus.FAILED
            failure = connected.failure
            if failure is None:
                raise RuntimeError("failed FAERS result omitted its failure")
            failure_id = derive_identity(
                "source-failure", {"query_id": query.query_id, "kind": failure.kind.value}
            )
            provider_as_of = None
        warnings = () if coverage is CoverageStatus.COMPLETE else ("incomplete_coverage",)
        outcome = SourceOutcome(
            source=SourceType.FAERS,
            query_id=query.query_id,
            execution_status=execution_status,
            coverage_status=coverage,
            result_status=result_status,
            configured_bounds=ExecutionBounds(
                max_query_characters=512,
                max_pages=5,
                max_records=100,
                max_payload_bytes=5_242_880,
                max_total_seconds=30,
            ),
            valid_result_count=len(buckets),
            pages_completed=connected.pages_completed,
            truncated=connected.truncated,
            warning_codes=warnings,
            failure_id=failure_id,
        )
        if any(
            item.termination_reason == "clock_integrity_failure" for item in connected.raw_responses
        ):
            raise SnapshotIntegrityError("FAERS response has an unpersistable clock failure")
        observations = tuple(
            RawResponseObservation(
                body=item.body,
                observed_at_utc=item.observed_at_utc,
                media_type="application/json",
                content_encoding=dict(item.headers).get("content-encoding"),
                http_status=item.status_code,
                body_complete=item.body_complete,
                termination_reason=item.termination_reason,  # type: ignore[arg-type]
            )
            for item in connected.raw_responses
        )
        snapshot_id = derive_identity(
            "snapshot", {"run_id": self._run_id, "intent_id": lifecycle.acquisition_intent_id}
        )
        captured = self._capture(
            lifecycle=lifecycle,
            query=query,
            snapshot_id=snapshot_id,
            completed=completed,
            outcome=outcome,
            provider_as_of=provider_as_of,
            buckets=buckets,
            observations=observations,
            attempts=max(1, connected.request_count),
        )
        result = FaersAggregateResult(
            query=query,
            buckets=buckets,
            source_outcome=outcome,
            retrieved_at_utc=completed,
            provider_as_of_utc=provider_as_of,
            snapshot_id=snapshot_id,
            manifest_id=captured.manifest.manifest_id,
        )
        source_outcome_id = derive_identity("source-operation-outcome", outcome)
        execution = FaersAggregateExecution(
            request=self._request.faers_query_requests[lifecycle.acquisition_ordinal],
            acquisition_outcome_ref=AcquisitionOutcomeRef(
                run_id=self._run_id,
                source=SourceType.FAERS,
                acquisition_id=lifecycle.acquisition_id,
                acquisition_intent_id=lifecycle.acquisition_intent_id,
                acquisition_ordinal=lifecycle.acquisition_ordinal,
                operation="search",
                query_id=query.query_id,
                source_outcome_id=source_outcome_id,
                snapshot_id=snapshot_id,
            ),
            result=result,
        )
        self._persist_rows(
            lifecycle,
            completed,
            captured,
            execution,
            source_outcome_id,
            observations,
        )
        projection = FaersAggregateExecutionProjection(
            run_id=self._run_id,
            scope_id=self._scope_id,
            task_id=self._task_id,
            attempt_id=self._attempt_id,
            execution=execution,
            bucket_evidence=tuple(
                FaersBucketEvidenceProjection(
                    bucket_ordinal=i,
                    evidence_id=e.evidence_id,
                    content_hash=e.content_hash,
                    locator_ref=e.locators[0],
                )
                for i, e in enumerate(
                    canonical_faers_bucket_evidence(execution, i) for i in range(len(buckets))
                )
            ),
        )
        data = canonical_json(projection).encode("utf-8")
        with SnapshotStore.writer(self._store):
            SnapshotStore.publish_source_replay(self._store, "faers-aggregate", data, **keys)
        provenance_store = VerifiedM1BEvidenceProvenanceStore(
            snapshots=self._store, repository=self._repository
        )
        envelopes = provenance_store.publish_faers(projection)
        if len(envelopes) != len(projection.bucket_evidence):
            raise SnapshotIntegrityError("FAERS normalized provenance count differs")
        for envelope, evidence_item in zip(envelopes, projection.bucket_evidence, strict=True):
            if (
                envelope.evidence_id != evidence_item.evidence_id
                or envelope.content_hash != evidence_item.content_hash
                or provenance_store.load_verified_provenance(
                    run_id=envelope.run_id,
                    evidence_id=envelope.evidence_id,
                    source=envelope.source,
                    source_record_id=envelope.source_record_id,
                    source_version=envelope.source_version,
                    snapshot_id=envelope.snapshot_id,
                    content_hash=envelope.content_hash,
                )
                is None
            ):
                raise SnapshotIntegrityError("FAERS normalized provenance readback differs")
        self._repository.finalize_m1b_acquisition(replace(lifecycle, completed_at_utc=completed))
        return self._load_execution(keys)

    def _capture(
        self,
        *,
        lifecycle: M1BAcquisitionLifecycle,
        query: FaersAggregateQueryV1,
        snapshot_id: str,
        completed: datetime,
        outcome: SourceOutcome,
        provider_as_of: datetime | None,
        buckets: tuple[FaersAggregateBucketV1, ...],
        observations: tuple[RawResponseObservation, ...],
        attempts: int,
    ) -> CapturedFaersSnapshot:
        with SnapshotStore.writer(self._store):
            return capture_faers_snapshot(
                self._store,
                run_id=self._run_id,
                acquisition_id=lifecycle.acquisition_id,
                acquisition_intent_id=lifecycle.acquisition_intent_id,
                acquisition_ordinal=lifecycle.acquisition_ordinal,
                query=query,
                snapshot_id=snapshot_id,
                started_at_utc=lifecycle.started_at_utc,
                completed_at_utc=completed,
                source_outcome=outcome,
                retrieved_at_utc=completed,
                provider_as_of_utc=provider_as_of,
                attempts_used=attempts,
                buckets=buckets,
                observations=observations,
                code_revision=self._code_revision,
                recognized_empty_response=recognized_empty_count_response,
            )

    def _persist_rows(
        self,
        lifecycle: M1BAcquisitionLifecycle,
        completed: datetime,
        captured: CapturedFaersSnapshot,
        execution: FaersAggregateExecution,
        outcome_id: str,
        observations: tuple[RawResponseObservation, ...],
    ) -> None:
        manifest = captured.manifest
        repo = self._repository
        repo.insert_or_verify_m1b_artifact(
            {
                "artifact_id": manifest.manifest_id,
                "artifact_kind": "faers_aggregate_manifest",
                "source_partition": "faers",
                "content_hash": manifest.manifest_id,
                "byte_size": len(manifest.canonical_bytes()),
                "media_type": "application/json",
                "relative_storage_label": captured.manifest_path.relative_to(
                    self._store.root
                ).as_posix(),
                "schema_version": manifest.manifest_schema_version,
                "created_at_utc": completed,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
            }
        )
        for member in manifest.members:
            repo.insert_or_verify_m1b_artifact(
                {
                    "artifact_id": member.artifact_id,
                    "artifact_kind": member.artifact_kind,
                    "source_partition": "faers",
                    "content_hash": member.content_hash,
                    "byte_size": member.byte_size,
                    "media_type": member.media_type,
                    "relative_storage_label": member.relative_path,
                    "schema_version": "m1b.faers.raw-response.v1",
                    "created_at_utc": completed,
                    "corpus_id": None,
                    "corpus_version": None,
                    "split": None,
                }
            )
        repo.insert_or_verify_m1b(
            "m1b_snapshots",
            {
                "query_id": manifest.query.query_id,
                "acquisition_intent_id": lifecycle.acquisition_intent_id,
                "acquisition_ordinal": lifecycle.acquisition_ordinal,
                "attempt_id": lifecycle.attempt_id,
                "run_id": lifecycle.run_id,
                "snapshot_id": manifest.snapshot_id,
                "acquisition_id": lifecycle.acquisition_id,
                "source": "faers",
                "manifest_artifact_id": manifest.manifest_id,
                "retrieved_at_utc": completed,
                "connector_version": "m1b-faers-002",
                "schema_version": "m1b.faers.snapshot.v1",
            },
        )
        for member, observation in zip(manifest.members, observations, strict=True):
            repo.insert_or_verify_m1b(
                "m1b_snapshot_artifacts",
                {
                    "acquisition_id": lifecycle.acquisition_id,
                    "source": "faers",
                    "run_id": lifecycle.run_id,
                    "snapshot_id": manifest.snapshot_id,
                    "ordinal": member.ordinal,
                    "link_id": member.link_id,
                    "artifact_id": member.artifact_id,
                    "content_hash": member.content_hash,
                    "body_complete": member.body_complete,
                    "termination_reason": member.termination_reason,
                    "http_status": member.http_status,
                    "observed_at_utc": observation.observed_at_utc,
                    "corpus_id": None,
                    "corpus_version": None,
                    "split": None,
                    "artifact_kind": member.artifact_kind,
                },
            )
        out = execution.result.source_outcome
        bounds = out.configured_bounds
        repo.insert_or_verify_m1b(
            "m1b_source_outcomes",
            {
                "source_outcome_id": outcome_id,
                "snapshot_id": manifest.snapshot_id,
                "run_id": lifecycle.run_id,
                "query_id": out.query_id,
                "acquisition_id": lifecycle.acquisition_id,
                "source": "faers",
                "acquisition_intent_id": lifecycle.acquisition_intent_id,
                "acquisition_ordinal": lifecycle.acquisition_ordinal,
                "operation": "search",
                "execution_status": out.execution_status.value,
                "coverage_status": out.coverage_status.value,
                "result_status": out.result_status.value,
                "max_query_characters": bounds.max_query_characters,
                "max_pages": bounds.max_pages,
                "max_records": bounds.max_records,
                "max_payload_bytes": bounds.max_payload_bytes,
                "max_total_seconds": bounds.max_total_seconds,
                "valid_result_count": out.valid_result_count,
                "pages_completed": out.pages_completed,
                "truncated": out.truncated,
                "failure_id": out.failure_id,
                "warning_codes": list(out.warning_codes),
                "schema_version": "1.0",
            },
        )
        repo.insert_or_verify_faers_result(
            run_id=lifecycle.run_id,
            acquisition_id=lifecycle.acquisition_id,
            result=execution.result,
        )

    def _publish_intent(self, intent: FaersSourceExecutionIntentV1) -> None:
        relative = _intent_relative_path(self._run_id, intent.acquisition_intent_id)
        with SnapshotStore.writer(self._store):
            SnapshotStore.publish_bytes(
                self._store, relative, intent.canonical_bytes(), artifact_class="journal"
            )
        raw = _read_exact_intent(self._store, relative)
        if raw != intent.canonical_bytes():
            raise SnapshotIntegrityError("FAERS source execution intent readback differs")

    def _load_intent(
        self, intent_id: str, query: FaersAggregateQueryV1
    ) -> FaersSourceExecutionIntentV1:
        relative = _intent_relative_path(self._run_id, intent_id)
        raw = _read_exact_intent(self._store, relative)
        if raw is None:
            raise SnapshotIntegrityError("FAERS source execution intent is missing")
        parsed = FaersSourceExecutionIntentV1.model_validate_json(raw, strict=False)
        intent = FaersSourceExecutionIntentV1.model_validate(
            parsed.model_dump(mode="python"), strict=True
        )
        if intent.canonical_bytes() != raw or (
            intent.acquisition_intent_id != intent_id
            or intent.run_id != self._run_id
            or intent.scope_id != self._scope_id
            or intent.task_id != self._task_id
            or intent.attempt_id != self._attempt_id
            or intent.query != query
            or intent.code_revision != self._code_revision
        ):
            raise SnapshotIntegrityError("FAERS source execution intent differs")
        return intent

    def _load_execution(self, keys: dict[str, str]) -> FaersAggregateExecution:
        raw = SnapshotStore.read_source_replay(self._store, "faers-aggregate", **keys)
        parsed = FaersAggregateExecutionProjection.model_validate_json(raw, strict=False)
        projection = FaersAggregateExecutionProjection.model_validate(
            parsed.model_dump(mode="python"), strict=True
        )
        if canonical_json(projection).encode("utf-8") != raw:
            raise SnapshotIntegrityError("FAERS execution replay is noncanonical")
        if (
            projection.run_id != self._run_id
            or projection.scope_id != self._scope_id
            or projection.task_id != self._task_id
            or projection.attempt_id != self._attempt_id
            or projection.execution.acquisition_outcome_ref.run_id != keys["run_id"]
            or projection.execution.acquisition_outcome_ref.query_id != keys["query_id"]
            or projection.execution.acquisition_outcome_ref.acquisition_intent_id
            != keys["acquisition_intent_id"]
        ):
            raise SnapshotIntegrityError("FAERS execution replay context differs")
        return projection.execution


__all__ = [
    "DailyMedCandidateEnrichmentPort",
    "DailyMedNativeDiscoveryRequestPort",
    "DailyMedSourceExecutionBridge",
    "FaersSourceExecutionBridge",
    "M1BSourceExecutionUnavailable",
]
