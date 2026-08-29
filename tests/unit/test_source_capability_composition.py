"""Production reachability tests for the closed source collection composition."""

from __future__ import annotations

import inspect
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest

from medevidence.composition import (
    _AcquisitionAdapter,
    _DailyMedReplayAdapter,
    _FaersReplayAdapter,
    create_source_evidence_collection,
)
from medevidence.domain import (
    AcquisitionOutcomeRef,
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    LabelSelectionStatus,
    M1BResearchRequestV1,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.infrastructure.cadec_local_search import (
    CadecLocalSearchAdapter,
    CanonicalCadecEvidenceCollection,
)
from medevidence.ingestion.snapshots import (
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.orchestration.contracts import (
    SourceOperationKind,
    SourceTaskState,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.source_capabilities import SourceCapabilities
from medevidence.persistence import PersistenceRepository
from medevidence.tools.contracts import (
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
    FaersAggregateExecution,
    ResearchPubMedRequest,
)
from medevidence.tools.dailymed import (
    DailyMedDiscoveryExecutionProjection,
    DailyMedFetchExecutionProjection,
)
from medevidence.tools.faers import FaersAggregateExecutionProjection
from medevidence.tools.ports import (
    PubMedSearchProgressRecord,
    PubMedTerminalOperationRecord,
    PubMedTerminalProgressRecord,
)
from medevidence.tools.research import PubMedResearchService

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"


def _scope() -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test reaction"),
        ),
        date_range=None,
        selected_sources=tuple(SourceType),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=1, max_total_seconds=30),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _source_request(scope: ResearchScope) -> M1BResearchRequestV1:
    return M1BResearchRequestV1(
        request_id="request:12345678-1234-4234-9234-123456789abc",
        scope=scope,
        requested_sources=scope.selected_sources,
        dailymed_selection_requests=(
            DailyMedSelectionRequestV1(
                drug_concept_id="rxnorm:1",
                requested_section_codes=("34084-4",),
                selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
            ),
        )
        if SourceType.DAILYMED in scope.selected_sources
        else (),
        faers_query_requests=(
            FaersAggregateRequestV1(
                drug_concept_id="rxnorm:1",
                identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
                identity_exact_value="SYNTHETIC INGREDIENT",
                pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
                inclusive_date_range=FaersInclusiveDateRangeV1(
                    start_date=date(2025, 1, 1),
                    end_date=date(2025, 1, 31),
                ),
                statistical_unit="provider_count_occurrence",
                execution_bounds=FaersExecutionBoundsV1(
                    max_date_difference_days=365,
                    max_inclusive_calendar_dates=366,
                ),
            ),
        )
        if SourceType.FAERS in scope.selected_sources
        else (),
    )


def _subset_scope(sources: tuple[SourceType, ...]) -> ResearchScope:
    base = _scope()
    return ResearchScope.create(
        drugs=base.drugs,
        adverse_reactions=base.adverse_reactions,
        date_range=base.date_range,
        selected_sources=sources,
        comparison_intent=base.comparison_intent,
        query_bounds=base.query_bounds,
        result_bounds=base.result_bounds,
    )


def _outcome(source: SourceType, query_id: str) -> SourceOutcome:
    bounds = (
        ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        )
        if source is SourceType.FAERS
        else ExecutionBounds.from_scope(_scope())
    )
    return SourceOutcome(
        source=source,
        query_id=query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=bounds,
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
    )


def _daily_replay_records() -> tuple[
    DailyMedDiscoveryExecutionProjection,
    DailyMedFetchExecutionProjection,
]:
    scope = _scope()
    selection = _source_request(scope).dailymed_selection_requests[0]
    task_id = source_task_id(RUN_ID, SourceType.DAILYMED)
    attempt_id = source_task_attempt(task_id, 1).attempt_id
    query_id = "query:daily-replay"
    discovery_response = DailyMedDiscoveryResponse(
        selection_request=selection,
        query_id=query_id,
        source_outcome_id="source-outcome:daily-discovery",
        source_outcome=_outcome(SourceType.DAILYMED, query_id),
        candidate_set_snapshot_id="snapshot:daily-discovery",
        discovery_manifest_id="artifact:daily-discovery",
        candidate_ids=(),
        decision_id="decision:daily-no-candidate",
        selection_status=LabelSelectionStatus.NO_CANDIDATE,
    )
    discovery = DailyMedDiscoveryExecutionProjection(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        task_id=task_id,
        attempt_id=attempt_id,
        response=discovery_response,
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:daily-discovery",
            acquisition_intent_id=f"acquisition-intent:sha256:{'a' * 64}",
            acquisition_ordinal=0,
            operation="search",
            query_id=query_id,
            source_outcome_id=discovery_response.source_outcome_id,
            snapshot_id=discovery_response.candidate_set_snapshot_id,
        ),
    )
    fetch_request = DailyMedFetchRequest(
        selection_request=selection,
        query_id=query_id,
        decision_id="decision:daily-selected",
        selected_candidate_id="candidate:daily-selected",
        selected_setid="00000000-0000-4000-8000-000000000001",
        selected_spl_version="1",
    )
    fetch_response = DailyMedFetchResponse(
        request=fetch_request,
        source_outcome_id="source-outcome:daily-fetch",
        source_outcome=_outcome(SourceType.DAILYMED, query_id),
        fetch_snapshot_id="snapshot:daily-fetch",
        fetch_manifest_id="artifact:daily-fetch",
    )
    fetch = DailyMedFetchExecutionProjection(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        task_id=task_id,
        attempt_id=attempt_id,
        response=fetch_response,
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:daily-fetch",
            acquisition_intent_id=f"acquisition-intent:sha256:{'b' * 64}",
            acquisition_ordinal=1,
            operation="fetch",
            query_id=query_id,
            source_outcome_id=fetch_response.source_outcome_id,
            snapshot_id=fetch_response.fetch_snapshot_id,
        ),
    )
    return discovery, fetch


def _faers_replay_record() -> FaersAggregateExecutionProjection:
    scope = _scope()
    request = _source_request(scope).faers_query_requests[0]
    query = FaersAggregateQueryV1.create(request)
    task_id = source_task_id(RUN_ID, SourceType.FAERS)
    attempt_id = source_task_attempt(task_id, 1).attempt_id
    result = FaersAggregateResult(
        query=query,
        buckets=(),
        source_outcome=_outcome(SourceType.FAERS, query.query_id),
        retrieved_at_utc=datetime(2026, 8, 29, tzinfo=UTC),
        provider_as_of_utc=None,
        snapshot_id="snapshot:faers-replay",
        manifest_id="artifact:faers-replay",
    )
    execution = FaersAggregateExecution(
        request=request,
        acquisition_outcome_ref=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.FAERS,
            acquisition_id="acquisition:faers-replay",
            acquisition_intent_id=f"acquisition-intent:sha256:{'c' * 64}",
            acquisition_ordinal=0,
            operation="search",
            query_id=query.query_id,
            source_outcome_id="source-outcome:faers-replay",
            snapshot_id=result.snapshot_id,
        ),
        result=result,
    )
    return FaersAggregateExecutionProjection(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        task_id=task_id,
        attempt_id=attempt_id,
        execution=execution,
    )


class _NoIoDailyProvenance:
    def load_discovery(self, **_values: object) -> object:
        raise AssertionError("composition must not perform DailyMed I/O")

    def load_fetch(self, **_values: object) -> object:
        raise AssertionError("composition must not perform DailyMed I/O")


class _NoIoFaersProvenance:
    def load_aggregate(self, **_values: object) -> object:
        raise AssertionError("composition must not perform FAERS I/O")


def test_composition_constructs_the_only_concrete_cadec_collection_route(
    tmp_path: Path,
) -> None:
    scope = _scope()
    request = ResearchPubMedRequest(
        request_id="request:12345678-1234-4234-9234-123456789abc",
        run_id=RUN_ID,
        created_at_utc=datetime(2026, 8, 29, tzinfo=UTC),
        code_revision="a" * 40,
        scope=scope,
    )
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
    repository = object.__new__(PersistenceRepository)
    collection = create_source_evidence_collection(
        pubmed_request=request,
        pubmed_catalog=cast(object, object()),
        pubmed_execution=cast(object, object()),
        snapshot_store=snapshots,
        persistence_repository=repository,
        code_revision=request.code_revision,
        attempt_id_factory=lambda: "attempt:00000000-0000-4000-8000-000000000001",
        utc_now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
        source_request=_source_request(scope),
        run_id=RUN_ID,
        dailymed_limitations=("Synthetic DailyMed limitation.",),
        dailymed_provenance=cast(object, _NoIoDailyProvenance()),
        dailymed_execution=cast(object, object()),
        faers_provenance=cast(object, _NoIoFaersProvenance()),
        faers_execution=cast(object, object()),
        faers_persistence=cast(object, object()),
        cadec_archive_path=Path("C:/approved/CADEC.v2.zip"),
        cadec_manifest_path=Path("C:/approved/manifest.json"),
    )

    assert type(collection) is CanonicalCadecEvidenceCollection
    assert type(collection._delegate) is SourceCapabilities
    assert type(collection._delegate._pubmed_service) is PubMedResearchService
    assert type(collection._delegate._pubmed_service._acquisitions) is _AcquisitionAdapter
    acquisitions = collection._delegate._pubmed_service._acquisitions
    assert acquisitions._store is snapshots
    assert acquisitions._repository is repository
    assert type(collection._delegate._dailymed_projection._replay_store) is _DailyMedReplayAdapter
    daily_replay = collection._delegate._dailymed_projection._replay_store
    assert daily_replay._store is snapshots
    assert type(collection._delegate._faers_projection._replay_store) is _FaersReplayAdapter
    faers_replay = collection._delegate._faers_projection._replay_store
    assert faers_replay._store is snapshots
    assert all(
        not hasattr(authority, "__dict__")
        for authority in (acquisitions, daily_replay, faers_replay)
    )
    for authority, name in (
        (acquisitions, "_store"),
        (acquisitions, "load_search_progress"),
        (acquisitions, "load_terminal_progress"),
        (daily_replay, "_store"),
        (daily_replay, "load_discovery"),
        (daily_replay, "load_fetch"),
        (faers_replay, "_store"),
        (faers_replay, "load_aggregate"),
    ):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(authority, name, object())
    pubmed_service = collection._delegate._pubmed_service
    for name in (
        "_acquisitions",
        "_catalog",
        "_execution",
        "_runs",
        "_runtime",
        "load_search_progress",
        "load_terminal_progress",
    ):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(pubmed_service, name, object())
    assert type(collection._search) is CadecLocalSearchAdapter
    assert not hasattr(collection._delegate, "_cadec_search")
    assert not hasattr(collection, "__dict__")
    task = SourceTaskState(
        task_id=source_task_id(RUN_ID, SourceType.CADEC),
        source=SourceType.CADEC,
    )
    operations = collection.plan_operations(
        task,
        scope,
        source_task_attempt(task.task_id, 1),
    )
    assert tuple(item.kind for item in operations) == (
        SourceOperationKind.CADEC_VERIFY,
        SourceOperationKind.CADEC_SEARCH,
    )

    class FakeSearch:
        calls = 0

        def search(self, **_values: object) -> object:
            self.calls += 1
            return object()

    fake = FakeSearch()
    with pytest.raises(AttributeError, match="frozen"):
        collection._search = cast(CadecLocalSearchAdapter, fake)
    with pytest.raises(AttributeError, match="frozen"):
        collection._delegate = cast(SourceCapabilities, object())
    with pytest.raises(AttributeError, match="frozen"):
        collection._search._archive_path = Path("C:/missing/fake.zip")
    with pytest.raises(AttributeError, match="frozen"):
        collection._search._manifest_path = Path("C:/missing/fake.json")
    with pytest.raises(AttributeError, match="frozen"):
        collection._search.search = fake.search  # type: ignore[method-assign]
    assert fake.calls == 0
    assert not snapshots.root.exists()


@pytest.mark.parametrize(
    "sources",
    tuple(
        tuple(source for index, source in enumerate(SourceType) if mask & (1 << index))
        for mask in range(1, 1 << len(SourceType))
    ),
)
def test_composition_constructs_exactly_each_nonempty_source_subset_without_io(
    tmp_path: Path,
    sources: tuple[SourceType, ...],
) -> None:
    scope = _subset_scope(sources)
    request = (
        ResearchPubMedRequest(
            request_id="request:12345678-1234-4234-9234-123456789abc",
            run_id=RUN_ID,
            created_at_utc=datetime(2026, 8, 29, tzinfo=UTC),
            code_revision="a" * 40,
            scope=scope,
        )
        if SourceType.PUBMED in sources
        else None
    )
    replaying = bool(set(sources) & {SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS})
    snapshots = (
        SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
        if replaying
        else None
    )
    repository = object.__new__(PersistenceRepository) if SourceType.PUBMED in sources else None
    collection = create_source_evidence_collection(
        source_request=_source_request(scope),
        run_id=RUN_ID,
        pubmed_request=request,
        pubmed_catalog=cast(object, object()) if SourceType.PUBMED in sources else None,
        pubmed_execution=cast(object, object()) if SourceType.PUBMED in sources else None,
        snapshot_store=snapshots,
        persistence_repository=repository,
        code_revision=request.code_revision if request is not None else None,
        attempt_id_factory=(
            (lambda: "attempt:00000000-0000-4000-8000-000000000001")
            if SourceType.PUBMED in sources
            else None
        ),
        utc_now=(
            (lambda: datetime(2026, 8, 29, tzinfo=UTC)) if SourceType.PUBMED in sources else None
        ),
        dailymed_limitations=(
            ("Synthetic DailyMed limitation.",) if SourceType.DAILYMED in sources else None
        ),
        dailymed_provenance=(
            cast(object, _NoIoDailyProvenance()) if SourceType.DAILYMED in sources else None
        ),
        dailymed_execution=(cast(object, object()) if SourceType.DAILYMED in sources else None),
        faers_provenance=(
            cast(object, _NoIoFaersProvenance()) if SourceType.FAERS in sources else None
        ),
        faers_execution=cast(object, object()) if SourceType.FAERS in sources else None,
        faers_persistence=cast(object, object()) if SourceType.FAERS in sources else None,
        cadec_archive_path=(
            Path("C:/approved/CADEC.v2.zip") if SourceType.CADEC in sources else None
        ),
        cadec_manifest_path=(
            Path("C:/approved/manifest.json") if SourceType.CADEC in sources else None
        ),
    )

    delegate = collection._delegate if SourceType.CADEC in sources else collection
    assert type(delegate) is SourceCapabilities
    assert type(collection) is (
        CanonicalCadecEvidenceCollection if SourceType.CADEC in sources else SourceCapabilities
    )
    assert delegate._sources == frozenset(set(sources) - {SourceType.CADEC})
    for source, attributes in (
        (SourceType.PUBMED, ("_pubmed_request", "_pubmed_service")),
        (SourceType.DAILYMED, ("_dailymed_projection", "_dailymed_execution")),
        (
            SourceType.FAERS,
            ("_faers_projection", "_faers_execution", "_faers_persistence"),
        ),
    ):
        assert all(hasattr(delegate, name) for name in attributes) is (source in sources)
    if snapshots is not None:
        assert not snapshots.root.exists()


def test_cadec_only_and_pubmed_only_require_no_foreign_source_dependencies(
    tmp_path: Path,
) -> None:
    cadec_scope = _subset_scope((SourceType.CADEC,))
    cadec = create_source_evidence_collection(
        source_request=_source_request(cadec_scope),
        run_id=RUN_ID,
        cadec_archive_path=Path("C:/approved/CADEC.v2.zip"),
        cadec_manifest_path=Path("C:/approved/manifest.json"),
    )
    assert type(cadec) is CanonicalCadecEvidenceCollection
    assert cadec._delegate._sources == frozenset()

    pubmed_scope = _subset_scope((SourceType.PUBMED,))
    request = ResearchPubMedRequest(
        request_id="request:12345678-1234-4234-9234-123456789abc",
        run_id=RUN_ID,
        created_at_utc=datetime(2026, 8, 29, tzinfo=UTC),
        code_revision="a" * 40,
        scope=pubmed_scope,
    )
    snapshots = SnapshotStore(tmp_path / "pubmed", free_bytes=lambda _path: 20_000_000_000)
    pubmed = create_source_evidence_collection(
        source_request=_source_request(pubmed_scope),
        run_id=RUN_ID,
        pubmed_request=request,
        pubmed_catalog=cast(object, object()),
        pubmed_execution=cast(object, object()),
        snapshot_store=snapshots,
        persistence_repository=object.__new__(PersistenceRepository),
        code_revision=request.code_revision,
        attempt_id_factory=lambda: "attempt:00000000-0000-4000-8000-000000000001",
        utc_now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert type(pubmed) is SourceCapabilities
    assert pubmed._sources == frozenset({SourceType.PUBMED})
    assert not snapshots.root.exists()


def test_composition_rejects_partial_extraneous_and_mismatched_source_groups(
    tmp_path: Path,
) -> None:
    cadec_scope = _subset_scope((SourceType.CADEC,))
    request = _source_request(cadec_scope)
    with pytest.raises(TypeError, match=r"pubmed.*extraneous"):
        create_source_evidence_collection(
            source_request=request,
            run_id=RUN_ID,
            pubmed_catalog=cast(object, object()),
            cadec_archive_path=Path("C:/approved/CADEC.v2.zip"),
            cadec_manifest_path=Path("C:/approved/manifest.json"),
        )

    daily_scope = _subset_scope((SourceType.DAILYMED,))
    with pytest.raises(TypeError, match=r"dailymed.*complete"):
        create_source_evidence_collection(
            source_request=_source_request(daily_scope),
            run_id=RUN_ID,
            snapshot_store=SnapshotStore(tmp_path / "daily"),
            dailymed_limitations=("Synthetic DailyMed limitation.",),
        )

    mismatched = _source_request(cadec_scope).model_copy(
        update={"requested_sources": (SourceType.PUBMED,)}
    )
    with pytest.raises(ValueError, match="requested_sources"):
        create_source_evidence_collection(
            source_request=mismatched,
            run_id=RUN_ID,
            cadec_archive_path=Path("C:/approved/CADEC.v2.zip"),
            cadec_manifest_path=Path("C:/approved/manifest.json"),
        )


def test_source_composition_has_no_prebuilt_pubmed_service_or_fake_store_route() -> None:
    parameters = inspect.signature(create_source_evidence_collection).parameters
    assert "pubmed_service" not in parameters
    assert "dailymed_replay_store" not in parameters
    assert "faers_replay_store" not in parameters
    assert tuple(parameters)[:9] == (
        "source_request",
        "run_id",
        "pubmed_request",
        "pubmed_catalog",
        "pubmed_execution",
        "snapshot_store",
        "persistence_repository",
        "code_revision",
        "attempt_id_factory",
    )
    scope = _scope()
    request = ResearchPubMedRequest(
        request_id="request:12345678-1234-4234-9234-123456789abc",
        run_id=RUN_ID,
        created_at_utc=datetime(2026, 8, 29, tzinfo=UTC),
        code_revision="a" * 40,
        scope=scope,
    )
    with pytest.raises(TypeError, match="exact concrete snapshot authority"):
        create_source_evidence_collection(
            pubmed_request=request,
            pubmed_catalog=cast(object, object()),
            pubmed_execution=cast(object, object()),
            snapshot_store=cast(SnapshotStore, object()),
            persistence_repository=cast(PersistenceRepository, object()),
            code_revision=request.code_revision,
            attempt_id_factory=lambda: "attempt:00000000-0000-4000-8000-000000000001",
            utc_now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
            source_request=_source_request(scope),
            run_id=RUN_ID,
            dailymed_limitations=("Synthetic DailyMed limitation.",),
            dailymed_provenance=cast(object, _NoIoDailyProvenance()),
            dailymed_execution=cast(object, object()),
            faers_provenance=cast(object, _NoIoFaersProvenance()),
            faers_execution=cast(object, object()),
            faers_persistence=cast(object, object()),
            cadec_archive_path=Path("C:/approved/CADEC.v2.zip"),
            cadec_manifest_path=Path("C:/approved/manifest.json"),
        )


def test_concrete_pubmed_receipts_round_trip_through_fresh_adapter(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
    repository = object.__new__(PersistenceRepository)
    first = _AcquisitionAdapter(
        store=snapshots,
        repository=repository,
        code_revision="a" * 40,
    )
    scope = _scope()
    query_id = "query:fixture"
    acquisition_intent_id = f"acquisition-intent:sha256:{'b' * 64}"
    snapshot_id = f"sha256:{'c' * 64}"
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id=query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=ExecutionBounds.from_scope(scope),
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
    )
    search = PubMedSearchProgressRecord.create(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        query="synthetic query",
        query_id=query_id,
        acquisition_intent_id=acquisition_intent_id,
        snapshot_id=snapshot_id,
        manifest_id=snapshot_id,
        pmids=(),
        search_source_outcome_id=derive_identity("source-operation-outcome", outcome),
        valid_result_count=0,
    )
    attempt_id = f"source-task-attempt:sha256:{'d' * 64}"
    terminal = PubMedTerminalProgressRecord.create(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        attempt_id=attempt_id,
        search_progress_record_id=search.record_id,
        search_progress_content_hash=search.content_hash,
        query_id=query_id,
        fetch_pmids=(),
        operations=(
            PubMedTerminalOperationRecord(
                ordinal=0,
                operation="search",
                acquisition_intent_id=acquisition_intent_id,
                snapshot_id=snapshot_id,
                source_outcome_id=derive_identity("source-operation-outcome", outcome),
                source_outcome=outcome,
            ),
        ),
        terminal_outcome=outcome,
        evidence=(),
        limitations=(),
    )
    with snapshots.writer():
        assert first.persist_search_progress(search) == search
        assert first.persist_terminal_progress(terminal) == terminal

    alternate_scope_id = f"scope:sha256:{'e' * 64}"
    alternate_search = PubMedSearchProgressRecord.create(
        **{**search.payload(), "scope_id": alternate_scope_id}
    )
    alternate_terminal = PubMedTerminalProgressRecord.create(
        run_id=terminal.run_id,
        scope_id=alternate_scope_id,
        attempt_id=terminal.attempt_id,
        search_progress_record_id=alternate_search.record_id,
        search_progress_content_hash=alternate_search.content_hash,
        query_id=terminal.query_id,
        fetch_pmids=terminal.fetch_pmids,
        operations=terminal.operations,
        terminal_outcome=terminal.terminal_outcome,
        evidence=terminal.evidence,
        limitations=terminal.limitations,
    )
    forged_calls: list[str] = []

    def forged_search_loader(*_args: object, **_kwargs: object) -> bytes:
        forged_calls.append("search")
        return alternate_search.artifact_bytes()

    def forged_terminal_loader(*_args: object, **_kwargs: object) -> bytes:
        forged_calls.append("terminal")
        return alternate_terminal.artifact_bytes()

    for name, loader in (
        ("read_pubmed_search_progress", forged_search_loader),
        ("read_pubmed_terminal_progress", forged_terminal_loader),
    ):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(snapshots, name, loader)
    assert forged_calls == []

    fresh = _AcquisitionAdapter(
        store=snapshots,
        repository=repository,
        code_revision="a" * 40,
    )
    assert (
        fresh.load_search_progress(
            run_id=RUN_ID,
            acquisition_intent_id=acquisition_intent_id,
        )
        == search
    )
    assert (
        fresh.load_terminal_progress(
            run_id=RUN_ID,
            attempt_id=attempt_id,
        )
        == terminal
    )
    terminal_path = (
        snapshots.root
        / "journal"
        / RUN_ID.removeprefix("run:")
        / "orchestration"
        / "pubmed"
        / attempt_id.removeprefix("source-task-attempt:sha256:")
        / "terminal-progress.json"
    )
    terminal_path.write_bytes(b"{}")
    with pytest.raises(SnapshotIntegrityError, match="failed exact validation"):
        fresh.load_terminal_progress(run_id=RUN_ID, attempt_id=attempt_id)


def test_internal_source_replay_adapters_persist_reload_and_reuse_exact_bytes(
    tmp_path: Path,
) -> None:
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
    discovery, fetch = _daily_replay_records()
    aggregate = _faers_replay_record()
    daily = _DailyMedReplayAdapter(snapshots)
    faers = _FaersReplayAdapter(snapshots)

    assert daily.persist_discovery(discovery) == discovery
    assert daily.persist_discovery(discovery) == discovery
    assert daily.persist_fetch(fetch) == fetch
    assert faers.persist_aggregate(aggregate) == aggregate

    fresh_daily = _DailyMedReplayAdapter(snapshots)
    assert (
        fresh_daily.load_discovery(
            acquisition_intent_id=discovery.acquisition.acquisition_intent_id,
            run_id=discovery.run_id,
            task_id=discovery.task_id,
            attempt_id=discovery.attempt_id,
            query_id=discovery.response.query_id,
        )
        == discovery
    )
    assert (
        fresh_daily.load_fetch(
            acquisition_intent_id=fetch.acquisition.acquisition_intent_id,
            run_id=fetch.run_id,
            task_id=fetch.task_id,
            attempt_id=fetch.attempt_id,
            query_id=fetch.response.request.query_id,
        )
        == fetch
    )
    assert (
        _FaersReplayAdapter(snapshots).load_aggregate(
            acquisition_intent_id=(
                aggregate.execution.acquisition_outcome_ref.acquisition_intent_id
            ),
            run_id=aggregate.run_id,
            task_id=aggregate.task_id,
            attempt_id=aggregate.attempt_id,
            query_id=aggregate.execution.result.query.query_id,
        )
        == aggregate
    )
    assert len(tuple(snapshots.root.rglob("projection.json"))) == 3
    assert not hasattr(daily, "__dict__")
    with pytest.raises(AttributeError):
        daily._store = SnapshotStore(tmp_path / "other")  # type: ignore[misc]


def test_source_replay_insert_conflict_corruption_and_cross_key_fail_closed(
    tmp_path: Path,
) -> None:
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
    record = _daily_replay_records()[0]
    replay = _DailyMedReplayAdapter(snapshots)
    replay.persist_discovery(record)
    key = {
        "acquisition_intent_id": record.acquisition.acquisition_intent_id,
        "run_id": record.run_id,
        "task_id": record.task_id,
        "attempt_id": record.attempt_id,
        "query_id": record.response.query_id,
    }
    conflict = record.model_copy(update={"scope_id": "scope:foreign"})
    with pytest.raises(SnapshotIntegrityError):
        replay.persist_discovery(conflict)

    exact = snapshots.read_source_replay("dailymed-discovery", **key)
    foreign_key = {**key, "query_id": "query:foreign-replay"}
    with snapshots.writer():
        snapshots.publish_source_replay("dailymed-discovery", exact, **foreign_key)
    with pytest.raises(SnapshotIntegrityError, match="another operation"):
        replay.load_discovery(**foreign_key)

    target = next(snapshots.root.rglob("projection.json"))
    target.write_bytes(json.dumps(json.loads(exact), indent=2).encode())
    with pytest.raises(SnapshotIntegrityError, match="not canonical"):
        replay.load_discovery(**key)
    target.write_bytes(b"{}")
    with pytest.raises(SnapshotIntegrityError, match="failed exact validation"):
        replay.load_discovery(**key)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_source_replay_load_rejects_reparse_leaf(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
    record = _faers_replay_record()
    replay = _FaersReplayAdapter(snapshots)
    replay.persist_aggregate(record)
    target = next(snapshots.root.rglob("projection.json"))
    outside = tmp_path / "foreign-projection.json"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")
    with pytest.raises(SnapshotContainmentError):
        replay.load_aggregate(
            acquisition_intent_id=(record.execution.acquisition_outcome_ref.acquisition_intent_id),
            run_id=record.run_id,
            task_id=record.task_id,
            attempt_id=record.attempt_id,
            query_id=record.execution.result.query.query_id,
        )


def test_cadec_wrapper_has_no_fake_port_result_or_callable_constructor_route() -> None:
    parameters = inspect.signature(CanonicalCadecEvidenceCollection).parameters
    assert tuple(parameters) == ("archive_path", "manifest_path", "delegate")
    with pytest.raises(TypeError, match="exact sealed three-source"):
        CanonicalCadecEvidenceCollection(
            archive_path=Path("C:/approved/CADEC.v2.zip"),
            manifest_path=Path("C:/approved/manifest.json"),
            delegate=cast(SourceCapabilities, object()),
        )
    with pytest.raises(TypeError, match="unexpected keyword"):
        CanonicalCadecEvidenceCollection(
            archive_path=Path("C:/approved/CADEC.v2.zip"),
            manifest_path=Path("C:/approved/manifest.json"),
            delegate=cast(SourceCapabilities, object()),
            search=object(),  # type: ignore[call-arg]
        )
