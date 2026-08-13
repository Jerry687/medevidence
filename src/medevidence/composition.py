"""Explicit M1A composition with optional additive M1B application seams."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import httpx
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from medevidence.api.app import ApiDependencies
from medevidence.api.errors import (
    ApplicationFailure,
    ArtifactIntegrityFailure,
    DeadlineExceededFailure,
    PersistenceIntegrityFailure,
    PersistenceUnavailableFailure,
    StorageBusyFailure,
    StorageCapacityFailure,
    ToolContractFailure,
)
from medevidence.catalog import ProductionCatalog, load_production_catalog
from medevidence.connectors.pubmed import (
    PubMedConnector,
    PubMedFetchResult,
    PubMedSearchResult,
    RawPubMedResponse,
)
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.domain import (
    CoverageStatus,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    M1BResearchReportV1,
    M1BResearchRequestV1,
    PublicationRecord,
    ResearchReport,
    ResearchScope,
    canonical_json,
    sha256_digest,
)
from medevidence.ingestion import (
    AcquisitionIntent,
    AcquisitionRegistrationEnvelope,
    RawResponseObservation,
    RunIntent,
    RunRegistrationEnvelope,
    capture_acquisition,
    response_observation,
    with_computed_identity,
)
from medevidence.ingestion.artifacts import CapturedAcquisition
from medevidence.ingestion.contracts import (
    AcquisitionExecutionLimits,
    AcquisitionRegistrationReference,
    ArtifactLinkReference,
    RunExecutionLimits,
)
from medevidence.ingestion.snapshots import (
    SnapshotBusyError,
    SnapshotCapacityError,
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.persistence import (
    AcquisitionRegistration,
    ArtifactLineageRow,
    ArtifactRow,
    PersistenceCapacityError,
    PersistenceConflict,
    PersistenceIntegrityError,
    PersistenceRepository,
    PersistenceSettings,
    PublicationVersionRow,
    ResearchReportRow,
    ResearchRunAttemptRow,
    ResearchRunRow,
    RunReportRegistration,
    SnapshotFileRow,
    SnapshotWarningRow,
    SourceSnapshotFileRow,
    SourceSnapshotPublicationRow,
    SourceSnapshotRow,
    ValidatedAcquisitionEnvelope,
    ValidatedArtifactLink,
    ValidatedManifest,
    ValidatedManifestFile,
)
from medevidence.tools import (
    PubMedResearchService,
    ResearchPubMedRequest,
    ResolvedConceptCatalog,
    SearchPubMedResponse,
    fetch_faers_aggregate,
    research_pubmed_draft,
)
from medevidence.tools.contracts import AcquisitionIntentInput, RunIntentInput
from medevidence.tools.ports import (
    AcquisitionFailureCode,
    FaersExecutionPort,
    FaersPersistencePort,
    FaersReportApplicationPort,
    PersistedAcquisition,
    PersistedPublicationBinding,
    PersistedPublicationLineageEdge,
    PubMedFetchExecution,
    PubMedSearchExecution,
    ResponseObservation,
    RunFinalization,
)

_EVIDENCE_HEADERS = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
    }
)


@dataclass(frozen=True, slots=True)
class _CatalogAdapter:
    catalog: ProductionCatalog
    scope: ResearchScope

    def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
        if scope_id != self.scope.scope_id:
            raise ValueError("catalog request does not match the active scope")
        return self.catalog.resolve_scope(self.scope)


@dataclass(frozen=True, slots=True)
class _RuntimeAdapter:
    attempt_id_factory: Callable[[], str]
    clock: Callable[[], datetime]

    def new_attempt_id(self) -> str:
        return self.attempt_id_factory()

    def utc_now(self) -> datetime:
        return self.clock()


@dataclass(frozen=True, slots=True)
class _ExecutionAdapter:
    connector: PubMedConnector
    clock: Callable[[], datetime]

    def search(self, *, query: str, query_id: str) -> PubMedSearchExecution:
        started = self.clock()
        result = self.connector.search(query, query_id=query_id)
        completed = self.clock()
        return _search_execution(result, started=started, completed=completed)

    def fetch(self, *, pmid: str, query_id: str) -> PubMedFetchExecution:
        started = self.clock()
        result = self.connector.fetch((pmid,), query_id=query_id)
        completed = self.clock()
        return _fetch_execution(result, pmid=pmid, started=started, completed=completed)


class _AcquisitionAdapter:
    def __init__(
        self,
        *,
        store: SnapshotStore,
        repository: PersistenceRepository,
        code_revision: str,
    ) -> None:
        self._store = store
        self._repository = repository
        self._code_revision = code_revision

    def persist_search(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: PubMedSearchExecution,
    ) -> PersistedAcquisition:
        return self._persist(
            intent=intent,
            outcome=execution.response.source_outcome,
            started_at_utc=execution.started_at_utc,
            completed_at_utc=execution.completed_at_utc,
            attempts_used=execution.attempts_used,
            observations=execution.observations,
            failure_code=execution.failure_code,
            redacted_detail=execution.redacted_detail,
            request_identity=execution.response.query_id,
            publications=(),
        )

    def persist_fetch(
        self,
        *,
        intent: AcquisitionIntentInput,
        execution: PubMedFetchExecution,
    ) -> PersistedAcquisition:
        publications = (execution.publication,) if execution.publication is not None else ()
        return self._persist(
            intent=intent,
            outcome=execution.source_outcome,
            started_at_utc=execution.started_at_utc,
            completed_at_utc=execution.completed_at_utc,
            attempts_used=execution.attempts_used,
            observations=execution.observations,
            failure_code=execution.failure_code,
            redacted_detail=execution.redacted_detail,
            request_identity=f"pubmed:{execution.requested_pmid}",
            publications=publications,
        )

    def _persist(
        self,
        *,
        intent: AcquisitionIntentInput,
        outcome: object,
        started_at_utc: datetime,
        completed_at_utc: datetime,
        attempts_used: int,
        observations: tuple[ResponseObservation, ...],
        failure_code: str | None,
        redacted_detail: str | None,
        request_identity: str,
        publications: tuple[PublicationRecord, ...],
    ) -> PersistedAcquisition:
        from medevidence.domain import SourceOutcome

        validated_outcome = SourceOutcome.model_validate(outcome, strict=True)
        captured_observations = (
            () if validated_outcome.coverage_status is CoverageStatus.UNAVAILABLE else observations
        )
        journal_directory = _acquisition_journal_directory(intent)
        journal_intent = _acquisition_intent_record(intent)
        if journal_intent.acquisition_intent_id != intent.acquisition_intent_id:
            raise ValueError("acquisition intent identity changed during composition")
        _write_journal(
            self._store,
            journal_directory,
            "acquisition-intent.json",
            journal_intent,
        )
        captured = capture_acquisition(
            self._store,
            journal_relative_directory=journal_directory,
            acquisition_intent_id=intent.acquisition_intent_id,
            request_identity=request_identity,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            validated_record_count=validated_outcome.valid_result_count,
            execution_status=validated_outcome.execution_status,
            coverage_status=validated_outcome.coverage_status,
            result_status=validated_outcome.result_status,
            attempts_used=attempts_used,
            pages_completed=validated_outcome.pages_completed,
            truncated=validated_outcome.truncated,
            warning_codes=validated_outcome.warning_codes,
            observations=tuple(_raw_observation(item) for item in captured_observations),
            code_revision=self._code_revision,
        )
        envelope = _acquisition_envelope(
            intent=intent,
            captured=captured,
            outcome=validated_outcome,
            attempts_used=attempts_used,
            failure_code=failure_code,
            redacted_detail=redacted_detail,
        )
        envelope_path = _write_journal(
            self._store,
            journal_directory,
            "registration-envelope.json",
            envelope,
        )
        registration, bindings = _acquisition_registration(
            store=self._store,
            intent=intent,
            captured=captured,
            envelope=envelope,
            envelope_path=envelope_path,
            publications=publications,
        )
        try:
            self._repository.register_acquisition(registration)
        except ValueError as error:
            raise PersistenceIntegrityError(
                "composed acquisition failed persistence validation"
            ) from error
        return PersistedAcquisition(
            acquisition_intent_id=intent.acquisition_intent_id,
            snapshot_id=captured.manifest.manifest_id,
            manifest_id=captured.manifest.manifest_id,
            registration_envelope_id=envelope.registration_envelope_id,
            publication_bindings=bindings,
        )


class _RunAdapter:
    def __init__(
        self,
        *,
        store: SnapshotStore,
        repository: PersistenceRepository,
    ) -> None:
        self._store = store
        self._repository = repository
        self._input: RunIntentInput | None = None
        self._record: RunIntent | None = None

    def persist_run_intent(self, intent: RunIntentInput) -> str:
        if self._input is not None:
            raise ValueError("run intent may be persisted only once")
        record = _run_intent_record(intent)
        _write_journal(
            self._store,
            _run_journal_directory(intent.run_id),
            "run-intent.json",
            record,
        )
        self._input = intent
        self._record = record
        return record.run_intent_id

    def persist_run_and_report(
        self,
        *,
        finalization: RunFinalization,
        acquisitions: tuple[PersistedAcquisition, ...],
    ) -> None:
        intent = self._input
        record = self._record
        if intent is None or record is None:
            raise ValueError("run finalization requires the persisted run intent")
        registration = _run_registration(
            store=self._store,
            intent=intent,
            run_intent=record,
            finalization=finalization,
            acquisitions=acquisitions,
        )
        try:
            self._repository.register_run_and_report(registration)
        except ValueError as error:
            raise PersistenceIntegrityError("composed run failed persistence validation") from error


def create_api_dependencies(
    *,
    snapshot_root: Path,
    persistence_settings: PersistenceSettings,
    code_revision: str,
    request_id_factory: Callable[[], str],
    run_id_factory: Callable[[], str],
    attempt_id_factory: Callable[[], str],
    utc_now: Callable[[], datetime],
    transport_factory: Callable[[], httpx.BaseTransport],
    dailymed_application: (Callable[[M1BResearchRequestV1], M1BResearchReportV1] | None) = None,
    faers_application: FaersReportApplicationPort | None = None,
) -> ApiDependencies:
    """Build deferred PubMed adapters and forward optional M1B applications."""

    resolved_root = snapshot_root.absolute()

    def application(request: ResearchPubMedRequest) -> ResearchReport:
        connector: PubMedConnector | None = None
        persistence: PersistenceRepository | None = None
        try:
            connector = PubMedConnector(
                transport_factory(),
                PubMedConnectorConfig.m1a_constrained_v1(),
                utc_now=utc_now,
            )
            store = SnapshotStore(resolved_root)
            persistence = PersistenceRepository(persistence_settings)
            runtime = _RuntimeAdapter(attempt_id_factory, utc_now)
            service = PubMedResearchService(
                catalog=_CatalogAdapter(load_production_catalog(), request.scope),
                execution=_ExecutionAdapter(connector, utc_now),
                acquisitions=_AcquisitionAdapter(
                    store=store,
                    repository=persistence,
                    code_revision=request.code_revision,
                ),
                runs=_RunAdapter(store=store, repository=persistence),
                runtime=runtime,
            )
            with store.writer():
                return research_pubmed_draft(request, service=service)
        except ApplicationFailure:
            raise
        except (SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise ArtifactIntegrityFailure() from error
        except (PersistenceConflict, PersistenceIntegrityError, IntegrityError) as error:
            raise PersistenceIntegrityFailure() from error
        except SnapshotBusyError as error:
            raise StorageBusyFailure() from error
        except SnapshotCapacityError as error:
            raise StorageCapacityFailure() from error
        except (PersistenceCapacityError, OperationalError, DBAPIError) as error:
            raise PersistenceUnavailableFailure() from error
        except TimeoutError as error:
            raise DeadlineExceededFailure() from error
        except ValueError as error:
            raise ToolContractFailure() from error
        finally:
            if persistence is not None:
                persistence.close()
            if connector is not None:
                connector.close()

    return ApiDependencies(
        application=application,
        request_id_factory=request_id_factory,
        run_id_factory=run_id_factory,
        utc_now=utc_now,
        code_revision=code_revision,
        dailymed_application=dailymed_application,
        faers_application=faers_application,
    )


def create_faers_aggregate_tool(
    *,
    execution: FaersExecutionPort,
    persistence: FaersPersistencePort,
) -> Callable[[FaersAggregateRequestV1], FaersAggregateResult]:
    """Bind injected FAERS ports without executing a request during construction."""

    def application(request: FaersAggregateRequestV1) -> FaersAggregateResult:
        return fetch_faers_aggregate(
            request,
            execution=execution,
            persistence=persistence,
        )

    return application


def _search_execution(
    result: PubMedSearchResult,
    *,
    started: datetime,
    completed: datetime,
) -> PubMedSearchExecution:
    if result.query_id is None or result.source_outcome is None:
        raise ValueError("connector search did not return a source outcome")
    observations = _response_observations(result.raw_responses)
    started, completed = _execution_times(started, completed, observations)
    failure_code, detail = _failure_fields(result.failure)
    return PubMedSearchExecution(
        response=SearchPubMedResponse(
            query=result.query,
            query_id=result.query_id,
            pmids=result.pmids,
            total_available=result.total_available,
            source_outcome=result.source_outcome,
        ),
        started_at_utc=started,
        completed_at_utc=completed,
        attempts_used=_attempts_used(result.request_count, result.raw_responses),
        observations=observations,
        failure_code=failure_code,
        redacted_detail=detail,
    )


def _fetch_execution(
    result: PubMedFetchResult,
    *,
    pmid: str,
    started: datetime,
    completed: datetime,
) -> PubMedFetchExecution:
    if result.query_id is None or result.source_outcome is None:
        raise ValueError("connector fetch did not return a source outcome")
    if len(result.publications) > 1:
        raise ValueError("singular connector fetch returned multiple publications")
    observations = _response_observations(result.raw_responses)
    started, completed = _execution_times(started, completed, observations)
    failure_code, detail = _failure_fields(result.failure)
    return PubMedFetchExecution(
        requested_pmid=pmid,
        query_id=result.query_id,
        publication=result.publications[0] if result.publications else None,
        source_outcome=result.source_outcome,
        started_at_utc=started,
        completed_at_utc=completed,
        attempts_used=_attempts_used(result.request_count, result.raw_responses),
        observations=observations,
        failure_code=failure_code,
        redacted_detail=detail,
    )


def _response_observations(
    raw_responses: tuple[RawPubMedResponse, ...],
) -> tuple[ResponseObservation, ...]:
    return tuple(
        ResponseObservation(
            body=item.body,
            observed_at_utc=item.observed_at_utc,
            headers=tuple(
                sorted((name, value) for name, value in item.headers if name in _EVIDENCE_HEADERS)
            ),
            http_status=item.status_code,
            body_complete=item.body_complete,
            termination_reason=item.termination_reason,
        )
        for item in raw_responses
    )


def _execution_times(
    started: datetime,
    completed: datetime,
    observations: tuple[ResponseObservation, ...],
) -> tuple[datetime, datetime]:
    observed = tuple(item.observed_at_utc for item in observations)
    return (
        min((started, *observed)),
        max((completed, *observed)),
    )


def _attempts_used(request_count: int, raw_responses: tuple[RawPubMedResponse, ...]) -> int:
    return min(2, max((1, request_count, *(item.attempt_count for item in raw_responses))))


def _failure_fields(
    failure: object,
) -> tuple[AcquisitionFailureCode | None, str | None]:
    if failure is None:
        return None, None
    from medevidence.connectors.pubmed import PubMedFailure

    value = cast(PubMedFailure, failure)
    return value.kind.value, value.message


def _raw_observation(observation: ResponseObservation) -> RawResponseObservation:
    return response_observation(
        body=observation.body,
        observed_at_utc=observation.observed_at_utc,
        headers=observation.headers,
        http_status=observation.http_status,
        body_complete=observation.body_complete,
        termination_reason=observation.termination_reason,
    )


def _run_journal_directory(run_id: str) -> str:
    return f"journal/{run_id.removeprefix('run:')}"


def _acquisition_journal_directory(intent: AcquisitionIntentInput) -> str:
    return f"{_run_journal_directory(intent.run_id)}/acquisition-{intent.acquisition_ordinal:04d}"


def _write_journal(
    store: SnapshotStore,
    directory: str,
    filename: str,
    record: object,
) -> Path:
    from medevidence.ingestion.artifacts import write_immutable_record
    from medevidence.ingestion.contracts import JournalModel

    return write_immutable_record(store, directory, filename, cast(JournalModel, record))


def _run_intent_record(intent: RunIntentInput) -> RunIntent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "run_id": intent.run_id,
        "request_id": intent.request_id,
        "created_at_utc": _utc_text(intent.created_at_utc),
        "code_revision": intent.code_revision,
        "scope_id": intent.scope_id,
        "execution_profile_id": "M1A_CONSTRAINED_V1",
        "catalog_version": intent.catalog_version,
        "source": "pubmed",
        "drug_concept_ids": intent.drug_concept_ids,
        "adverse_event_concept_ids": intent.adverse_event_concept_ids,
        "pubmed_query": intent.pubmed_query,
        "execution_limits": RunExecutionLimits().model_dump(mode="json"),
    }
    if intent.start_date is not None:
        payload["start_date"] = intent.start_date.isoformat()
        assert intent.end_date is not None
        payload["end_date"] = intent.end_date.isoformat()
    return cast(RunIntent, with_computed_identity(RunIntent, payload))


def _acquisition_intent_record(intent: AcquisitionIntentInput) -> AcquisitionIntent:
    request: dict[str, object]
    if intent.operation == "search":
        request = {
            "db": "pubmed",
            "path": "/entrez/eutils/esearch.fcgi",
            "retmax": 100,
            "retmode": "xml",
            "retstart": 0,
            "term": intent.query,
        }
    else:
        request = {
            "db": "pubmed",
            "id": intent.pmid,
            "path": "/entrez/eutils/efetch.fcgi",
            "retmode": "xml",
            "rettype": "abstract",
        }
    return cast(
        AcquisitionIntent,
        with_computed_identity(
            AcquisitionIntent,
            {
                "schema_version": "1.0",
                "attempt_id": intent.attempt_id,
                "run_id": intent.run_id,
                "run_intent_id": intent.run_intent_id,
                "created_at_utc": _utc_text(intent.created_at_utc),
                "execution_profile_id": "M1A_CONSTRAINED_V1",
                "source": "pubmed",
                "operation": intent.operation,
                "acquisition_ordinal": intent.acquisition_ordinal,
                "request": request,
                "execution_limits": AcquisitionExecutionLimits().model_dump(mode="json"),
            },
        ),
    )


def _acquisition_envelope(
    *,
    intent: AcquisitionIntentInput,
    captured: CapturedAcquisition,
    outcome: object,
    attempts_used: int,
    failure_code: str | None,
    redacted_detail: str | None,
) -> AcquisitionRegistrationEnvelope:
    from medevidence.domain import SourceOutcome

    validated = SourceOutcome.model_validate(outcome, strict=True)
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "envelope_kind": "acquisition",
        "acquisition_intent_id": intent.acquisition_intent_id,
        "acquisition_ordinal": intent.acquisition_ordinal,
        "attempt_id": intent.attempt_id,
        "run_id": intent.run_id,
        "source": "pubmed",
        "operation": intent.operation,
        "started_at_utc": _utc_text(captured.manifest.started_at_utc),
        "completed_at_utc": _utc_text(captured.manifest.completed_at_utc),
        "execution_status": validated.execution_status.value,
        "coverage_status": validated.coverage_status.value,
        "result_status": validated.result_status.value,
        "valid_result_count": validated.valid_result_count,
        "pages_completed": validated.pages_completed,
        "attempts_used": attempts_used,
        "truncated": validated.truncated,
        "warning_codes": validated.warning_codes,
        "artifact_links": tuple(
            ArtifactLinkReference(ordinal=item.ordinal, link_id=item.link_id).model_dump(
                mode="json"
            )
            for item in captured.artifact_links
        ),
        "manifest_id": captured.manifest.manifest_id,
        "registration_state": "ready_for_insert",
    }
    if failure_code is not None:
        payload["failure_code"] = failure_code
        payload["redacted_detail"] = redacted_detail
    return cast(
        AcquisitionRegistrationEnvelope,
        with_computed_identity(AcquisitionRegistrationEnvelope, payload),
    )


def _acquisition_registration(
    *,
    store: SnapshotStore,
    intent: AcquisitionIntentInput,
    captured: CapturedAcquisition,
    envelope: AcquisitionRegistrationEnvelope,
    envelope_path: Path,
    publications: tuple[PublicationRecord, ...],
) -> tuple[AcquisitionRegistration, tuple[PersistedPublicationBinding, ...]]:
    manifest = captured.manifest
    manifest_bytes = manifest.canonical_bytes()
    manifest_artifact = _artifact_row(
        path=captured.manifest_path,
        data=manifest_bytes,
        kind="snapshot_manifest",
        partition="pubmed",
        media_type="application/json",
        store=store,
    )
    envelope_artifact = _artifact_row(
        path=envelope_path,
        data=envelope.canonical_bytes(),
        kind="acquisition_registration_envelope",
        partition="pubmed",
        media_type="application/json",
        store=store,
    )
    raw_artifacts = tuple(
        ArtifactRow(
            artifact_id=link.artifact_id,
            artifact_kind="pubmed_http_response",
            source_partition="pubmed",
            content_hash=link.artifact_id,
            byte_size=link.byte_size,
            media_type=link.media_type,
            relative_storage_path=item.relative_path,
            artifact_schema_version="1.0",
        )
        for link, item in zip(captured.artifact_links, manifest.files, strict=True)
    )
    publication_rows: list[PublicationVersionRow] = []
    publication_artifacts: list[ArtifactRow] = []
    for publication in publications:
        payload = cast(
            dict[str, object],
            json.loads(canonical_json(publication.version_payload())),
        )
        raw = canonical_json(payload).encode("utf-8")
        digest = publication.content_hash.removeprefix("sha256:")
        published = store.publish_bytes(
            f"pubmed/publications/sha256/{digest[:2]}/{digest}.json",
            raw,
            artifact_class="journal",
        )
        publication_artifacts.append(
            _artifact_row(
                path=published.path,
                data=raw,
                kind="publication_record",
                partition="pubmed",
                media_type="application/json",
                store=store,
            )
        )
        publication_rows.append(
            PublicationVersionRow(
                publication_version_id=publication.publication_version_id,
                source="pubmed",
                pmid=publication.pmid,
                content_hash=publication.content_hash,
                publication_status_identity=(
                    publication.publication_status.publication_status_identity
                ),
                publication_status=publication.publication_status.status.value,
                status_retrieved_at_utc=publication.publication_status.retrieved_as_of,
                version_payload=payload,
                publication_artifact_id=publication.content_hash,
                publication_artifact_kind="publication_record",
                publication_source_partition="pubmed",
                publication_artifact_hash=publication.content_hash,
                schema_version="1.0",
            )
        )
    snapshot = SourceSnapshotRow(
        snapshot_id=manifest.manifest_id,
        source="pubmed",
        acquisition_intent_id=intent.acquisition_intent_id,
        request_identity=manifest.request_identity,
        execution_status=manifest.execution_status.value,
        coverage_status=manifest.coverage_status.value,
        result_status=manifest.result_status.value,
        record_count=manifest.record_count,
        attempts_used=manifest.attempts_used,
        pages_completed=manifest.pages_completed,
        truncated=manifest.truncated,
        manifest_artifact_id=manifest.manifest_id,
        manifest_artifact_kind="snapshot_manifest",
        manifest_source_partition="pubmed",
        manifest_content_hash=manifest.manifest_id,
        started_at_utc=manifest.started_at_utc,
        completed_at_utc=manifest.completed_at_utc,
        connector_name=manifest.connector_name,
        connector_version=manifest.connector_version,
        manifest_schema_version=manifest.manifest_schema_version,
        source_record_schema_version=manifest.source_record_schema_version,
        code_revision=manifest.code_revision,
        retention_policy_id=manifest.retention_policy_id,
    )
    links = tuple(
        ValidatedArtifactLink(
            link_id=link.link_id,
            acquisition_intent_id=link.acquisition_intent_id,
            ordinal=link.ordinal,
            artifact_id=link.artifact_id,
            artifact_kind=link.artifact_kind,
            media_type=link.media_type,
            content_encoding=link.content_encoding,
            http_status=link.http_status,
            byte_size=link.byte_size,
            body_complete=link.body_complete,
            termination_reason=link.termination_reason,
            observed_at_utc=link.observed_at_utc,
            schema_version=link.schema_version,
        )
        for link in captured.artifact_links
    )
    files = tuple(
        SnapshotFileRow(
            link_id=link.link_id,
            acquisition_intent_id=link.acquisition_intent_id,
            ordinal=link.ordinal,
            raw_artifact_id=link.artifact_id,
            raw_artifact_kind=link.artifact_kind,
            raw_source_partition="pubmed",
            raw_content_hash=link.artifact_id,
            relative_storage_path=item.relative_path,
            byte_size=link.byte_size,
            media_type=link.media_type,
            content_encoding=link.content_encoding,
            http_status=link.http_status,
            body_complete=link.body_complete,
            termination_reason=link.termination_reason,
            observed_at_utc=link.observed_at_utc,
            schema_version=link.schema_version,
        )
        for link, item in zip(links, manifest.files, strict=True)
    )
    memberships = tuple(
        SourceSnapshotFileRow(
            snapshot_id=manifest.manifest_id,
            acquisition_intent_id=intent.acquisition_intent_id,
            ordinal=link.ordinal,
            link_id=link.link_id,
        )
        for link in links
    )
    publication_memberships = tuple(
        SourceSnapshotPublicationRow(
            snapshot_id=manifest.manifest_id,
            publication_ordinal=ordinal,
            pmid=row["pmid"],
            publication_version_id=row["publication_version_id"],
            source=row["source"],
            publication_content_hash=row["content_hash"],
        )
        for ordinal, row in enumerate(publication_rows)
    )
    lineage = tuple(
        ArtifactLineageRow(
            parent_artifact_id=manifest.manifest_id,
            parent_artifact_kind="snapshot_manifest",
            parent_source_partition="pubmed",
            parent_content_hash=manifest.manifest_id,
            child_artifact_id=link.artifact_id,
            child_artifact_kind="pubmed_http_response",
            child_source_partition="pubmed",
            child_content_hash=link.artifact_id,
            lineage_type="manifest_to_raw_response",
            lineage_ordinal=link.ordinal,
            schema_version="1.0",
        )
        for link in links
    ) + tuple(
        ArtifactLineageRow(
            parent_artifact_id=row["publication_artifact_id"],
            parent_artifact_kind="publication_record",
            parent_source_partition="pubmed",
            parent_content_hash=row["publication_artifact_hash"],
            child_artifact_id=manifest.manifest_id,
            child_artifact_kind="snapshot_manifest",
            child_source_partition="pubmed",
            child_content_hash=manifest.manifest_id,
            lineage_type="publication_to_manifest",
            lineage_ordinal=ordinal,
            schema_version="1.0",
        )
        for ordinal, row in enumerate(publication_rows)
    )
    attempt = ResearchRunAttemptRow(
        attempt_id=intent.attempt_id,
        run_id=intent.run_id,
        acquisition_ordinal=intent.acquisition_ordinal,
        acquisition_intent_id=intent.acquisition_intent_id,
        registration_envelope_id=envelope.registration_envelope_id,
        source="pubmed",
        operation=intent.operation,
        intent_created_at_utc=intent.created_at_utc,
        request_identity=manifest.request_identity,
        execution_profile_id="M1A_CONSTRAINED_V1",
        started_at_utc=manifest.started_at_utc,
        completed_at_utc=manifest.completed_at_utc,
        execution_status=manifest.execution_status.value,
        coverage_status=manifest.coverage_status.value,
        result_status=manifest.result_status.value,
        valid_result_count=manifest.record_count,
        pages_completed=manifest.pages_completed,
        attempts_used=manifest.attempts_used,
        truncated=manifest.truncated,
        warning_codes=manifest.warning_codes,
        failure_code=envelope.failure_code,
        redacted_detail=envelope.redacted_detail,
        registration_state=envelope.registration_state,
        manifest_id=manifest.manifest_id,
        envelope_artifact_id=envelope_artifact["artifact_id"],
        envelope_artifact_kind="acquisition_registration_envelope",
        envelope_source_partition="pubmed",
        envelope_content_hash=envelope_artifact["content_hash"],
        intent_schema_version=intent.schema_version,
        envelope_schema_version=envelope.schema_version,
    )
    validated_manifest = ValidatedManifest(
        manifest_id=manifest.manifest_id,
        manifest_schema_version=manifest.manifest_schema_version,
        retention_policy_id=manifest.retention_policy_id,
        source_type=manifest.source_type,
        acquisition_intent_id=manifest.acquisition_intent_id,
        request_identity=manifest.request_identity,
        started_at_utc=manifest.started_at_utc,
        completed_at_utc=manifest.completed_at_utc,
        record_count=manifest.record_count,
        execution_status=manifest.execution_status.value,
        coverage_status=manifest.coverage_status.value,
        result_status=manifest.result_status.value,
        attempts_used=manifest.attempts_used,
        pages_completed=manifest.pages_completed,
        truncated=manifest.truncated,
        warning_codes=manifest.warning_codes,
        files=tuple(
            ValidatedManifestFile(
                ordinal=item.ordinal,
                link_id=item.link_id,
                artifact_id=item.artifact_id,
                relative_path=item.relative_path,
                byte_size=item.byte_size,
                media_type=item.media_type,
                content_encoding=item.content_encoding,
                http_status=item.http_status,
                body_complete=item.body_complete,
                termination_reason=item.termination_reason,
            )
            for item in manifest.files
        ),
        connector_name=manifest.connector_name,
        connector_version=manifest.connector_version,
        source_record_schema_version=manifest.source_record_schema_version,
        code_revision=manifest.code_revision,
    )
    artifacts = _unique_artifacts(
        (
            manifest_artifact,
            envelope_artifact,
            *raw_artifacts,
            *publication_artifacts,
        )
    )
    registration = AcquisitionRegistration(
        artifacts=artifacts,
        snapshot=snapshot,
        files=files,
        memberships=memberships,
        warnings=tuple(
            SnapshotWarningRow(
                snapshot_id=manifest.manifest_id,
                warning_ordinal=ordinal,
                warning_code=code,
            )
            for ordinal, code in enumerate(manifest.warning_codes)
        ),
        publications=tuple(publication_rows),
        publication_memberships=publication_memberships,
        lineage=lineage,
        attempt=attempt,
        manifest=validated_manifest,
        artifact_links=links,
        envelope=ValidatedAcquisitionEnvelope(
            attempt=attempt,
            publications=tuple(publication_rows),
            publication_memberships=publication_memberships,
            lineage=lineage,
        ),
    )
    bindings = tuple(
        PersistedPublicationBinding(
            pmid=row["pmid"],
            publication_version_id=row["publication_version_id"],
            publication_artifact_id=row["publication_artifact_id"],
            snapshot_id=manifest.manifest_id,
            manifest_id=manifest.manifest_id,
            artifact_ids=tuple(sorted({row["publication_artifact_id"], manifest.manifest_id})),
            lineage_edges=(
                PersistedPublicationLineageEdge(
                    parent_artifact_id=row["publication_artifact_id"],
                    child_artifact_id=manifest.manifest_id,
                ),
            ),
        )
        for row in publication_rows
    )
    return registration, bindings


def _run_registration(
    *,
    store: SnapshotStore,
    intent: RunIntentInput,
    run_intent: RunIntent,
    finalization: RunFinalization,
    acquisitions: tuple[PersistedAcquisition, ...],
) -> RunReportRegistration:
    report = finalization.report
    outcome = report.source_outcomes[0]
    report_raw = finalization.report_artifact_bytes
    report_digest = report.report_artifact_id.removeprefix("sha256:")
    published_report = store.publish_bytes(
        f"reports/sha256/{report_digest[:2]}/{report_digest}.json",
        report_raw,
        artifact_class="journal",
    )
    report_artifact = _artifact_row(
        path=published_report.path,
        data=report_raw,
        kind="research_report",
        partition="global",
        media_type="application/json",
        store=store,
    )
    run_envelope = cast(
        RunRegistrationEnvelope,
        with_computed_identity(
            RunRegistrationEnvelope,
            {
                "schema_version": "1.0",
                "envelope_kind": "run",
                "run_intent_id": run_intent.run_intent_id,
                "run_id": intent.run_id,
                "started_at_utc": _utc_text(finalization.started_at_utc),
                "completed_at_utc": _utc_text(finalization.completed_at_utc),
                "run_status": (
                    "completed" if outcome.coverage_status.value == "complete" else "degraded"
                ),
                "coverage_status": outcome.coverage_status.value,
                "result_status": outcome.result_status.value,
                "acquisition_registrations": tuple(
                    AcquisitionRegistrationReference(
                        acquisition_registration_envelope_id=(acquisition.registration_envelope_id),
                        run_ordinal=ordinal,
                    ).model_dump(mode="json")
                    for ordinal, acquisition in enumerate(acquisitions)
                ),
                "report_id": report.report_id,
                "report_artifact_id": report.report_artifact_id,
                "report_media_type": "application/json",
                "report_byte_size": len(report_raw),
                "report_status": "draft",
                "warning_codes": finalization.warning_codes,
                "registration_state": "ready_for_insert",
            },
        ),
    )
    envelope_path = _write_journal(
        store,
        _run_journal_directory(intent.run_id),
        "registration-envelope.json",
        run_envelope,
    )
    envelope_artifact = _artifact_row(
        path=envelope_path,
        data=run_envelope.canonical_bytes(),
        kind="run_registration_envelope",
        partition="global",
        media_type="application/json",
        store=store,
    )
    run = ResearchRunRow(
        run_id=intent.run_id,
        run_intent_id=run_intent.run_intent_id,
        request_id=intent.request_id,
        created_at_utc=intent.created_at_utc,
        code_revision=intent.code_revision,
        scope_id=intent.scope_id,
        execution_profile_id="M1A_CONSTRAINED_V1",
        catalog_version=intent.catalog_version,
        catalog_content_hash=intent.catalog_content_hash,
        source="pubmed",
        drug_concept_ids=intent.drug_concept_ids,
        adverse_event_concept_ids=intent.adverse_event_concept_ids,
        start_date=intent.start_date,
        end_date=intent.end_date,
        pubmed_query=intent.pubmed_query,
        started_at_utc=finalization.started_at_utc,
        completed_at_utc=finalization.completed_at_utc,
        run_status=("completed" if outcome.coverage_status.value == "complete" else "degraded"),
        coverage_status=outcome.coverage_status.value,
        result_status=outcome.result_status.value,
        registration_envelope_id=run_envelope.registration_envelope_id,
        envelope_artifact_id=envelope_artifact["artifact_id"],
        envelope_artifact_kind="run_registration_envelope",
        envelope_source_partition="global",
        envelope_content_hash=envelope_artifact["content_hash"],
        report_id=report.report_id,
        warning_codes=finalization.warning_codes,
    )
    report_row = ResearchReportRow(
        report_id=report.report_id,
        run_id=report.run_id,
        report_status="draft",
        report_artifact_id=report.report_artifact_id,
        report_artifact_kind="research_report",
        report_source_partition="global",
        report_content_hash=report.report_artifact_id,
        report_byte_size=len(report_raw),
        report_media_type="application/json",
        created_at_utc=finalization.completed_at_utc,
        schema_version=report.schema_version,
        coverage_status=outcome.coverage_status.value,
        result_status=outcome.result_status.value,
    )
    lineage = (
        ArtifactLineageRow(
            parent_artifact_id=envelope_artifact["artifact_id"],
            parent_artifact_kind="run_registration_envelope",
            parent_source_partition="global",
            parent_content_hash=envelope_artifact["content_hash"],
            child_artifact_id=report.report_artifact_id,
            child_artifact_kind="research_report",
            child_source_partition="global",
            child_content_hash=report.report_artifact_id,
            lineage_type="run_envelope_to_report",
            lineage_ordinal=0,
            schema_version="1.0",
        ),
        *(
            ArtifactLineageRow(
                parent_artifact_id=report.report_artifact_id,
                parent_artifact_kind="research_report",
                parent_source_partition="global",
                parent_content_hash=report.report_artifact_id,
                child_artifact_id=publication.content_hash,
                child_artifact_kind="publication_record",
                child_source_partition="pubmed",
                child_content_hash=publication.content_hash,
                lineage_type="report_to_publication",
                lineage_ordinal=ordinal,
                schema_version="1.0",
            )
            for ordinal, publication in enumerate(report.publications)
        ),
    )
    return RunReportRegistration(
        artifacts=(envelope_artifact, report_artifact),
        run=run,
        report=report_row,
        lineage=lineage,
        acquisition_references=tuple(
            (ordinal, acquisition.registration_envelope_id)
            for ordinal, acquisition in enumerate(acquisitions)
        ),
    )


def _artifact_row(
    *,
    path: Path,
    data: bytes,
    kind: str,
    partition: str,
    media_type: str,
    store: SnapshotStore,
) -> ArtifactRow:
    identity = sha256_digest(data)
    return ArtifactRow(
        artifact_id=identity,
        artifact_kind=kind,
        source_partition=partition,
        content_hash=identity,
        byte_size=len(data),
        media_type=media_type,
        relative_storage_path=path.relative_to(store.root).as_posix(),
        artifact_schema_version="1.0",
    )


def _unique_artifacts(artifacts: tuple[ArtifactRow, ...]) -> tuple[ArtifactRow, ...]:
    by_id: dict[str, ArtifactRow] = {}
    for artifact in artifacts:
        existing = by_id.setdefault(artifact["artifact_id"], artifact)
        if existing != artifact:
            raise ValueError("content identity has conflicting artifact metadata")
    return tuple(by_id.values())


def _utc_text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = ["create_api_dependencies", "create_faers_aggregate_tool"]
