from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from tests.unit.orchestration.test_dailymed_faers_capability import _faers_request, _scope

from medevidence.composition import _FaersReplayAdapter
from medevidence.domain import (
    FaersAggregateQueryV1,
    FaersIdentityStrategy,
    M1BResearchRequestV1,
    SourceType,
)
from medevidence.infrastructure.dailymed_v2_provenance import DailyMedV2ProvenanceStore
from medevidence.infrastructure.dailymed_v2_record_store import DailyMedV2RecordStore
from medevidence.infrastructure.evidence_provenance import VerifiedEvidenceProvenanceStore
from medevidence.infrastructure.local_source_runtime import (
    LocalSourceEvidenceCollection,
    VerifiedSourceMaterialReader,
)
from medevidence.infrastructure.m1b_evidence_provenance import (
    VerifiedM1BEvidenceProvenanceStore,
)
from medevidence.infrastructure.m1b_source_execution import (
    FaersSourceExecutionBridge,
    M1BSourceExecutionUnavailable,
)
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    SourceTaskState,
    SourceTaskStatus,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.dailymed_faers_capability import CanonicalFaersProjectionAuthority
from medevidence.orchestration.source_capabilities import SourceCapabilities, terminal_source_task
from medevidence.persistence import PersistenceRepository, PersistenceSettings
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.dailymed_v2 import DailyMedV2Repository
from medevidence.persistence.models import (
    m1b_acquisitions,
    m1b_artifacts,
    m1b_faers_buckets,
    m1b_faers_queries,
    m1b_runs,
    m1b_snapshot_artifacts,
    m1b_snapshots,
    m1b_source_outcomes,
    m3_evidence_provenance,
)
from medevidence.persistence.repositories import M1BRunLifecycle, PersistenceConflict
from medevidence.tools.faers import FaersAggregateExecutionProjection


def _url() -> str:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    return value


@pytest.mark.parametrize("status", (200, 404, 400))
def test_real_faers_bridge_starts_before_mock_io_and_replays_without_resend(
    tmp_path: Path,
    status: int,
) -> None:
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    identity = uuid4()
    run_id = f"run:{identity}"
    request_id = f"request:{identity}"
    attempt_id = source_task_attempt(source_task_id(run_id, SourceType.FAERS), 1).attempt_id
    scope = _scope(SourceType.FAERS)
    faers_request = _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    request = M1BResearchRequestV1(
        request_id=request_id,
        scope=scope,
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=(faers_request,),
    )
    raw = (
        (Path(__file__).parents[2] / "fixtures" / "faers" / "count-single-bucket.json").read_bytes()
        if status == 200
        else b'{"error":{"code":"NOT_FOUND","message":"No matches found!"}}'
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=raw)

    now = datetime(2026, 9, 15, tzinfo=UTC)
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    store = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    bridge = FaersSourceExecutionBridge(
        run_id=run_id,
        scope=scope,
        request=request,
        task_id=source_task_id(run_id, SourceType.FAERS),
        attempt_id=attempt_id,
        clock=lambda: now,
        code_revision="a" * 40,
        transport_factory=lambda: httpx.MockTransport(handler),
        store=store,
        repository=repository,
    )
    query = FaersAggregateQueryV1.create(faers_request)
    artifact_ids: tuple[str, ...] = ()
    try:
        first = bridge.execute(query)
        assert calls == 1
        assert first.result.source_outcome.result_status.value == (
            "matches" if status == 200 else "no_match" if status == 404 else "indeterminate"
        )
        assert first.result.source_outcome.truncated is False
        assert bridge.persist(first).execution == first
        provenance = bridge.load_aggregate(execution=first)
        assert len(provenance.bucket_evidence) == (1 if status == 200 else 0)
        task_id = source_task_id(run_id, SourceType.FAERS)
        attempt = source_task_attempt(task_id, 1)
        capability = SourceCapabilities(
            faers_projection=CanonicalFaersProjectionAuthority(
                request=request,
                run_id=run_id,
                provenance=bridge,
                replay_store=_FaersReplayAdapter(store),
            ),
            faers_execution=bridge,
            faers_persistence=bridge,
        )
        source_collection = LocalSourceEvidenceCollection(
            base=SourceCapabilities(),
            snapshots=store,
            dailymed_v2=None,
            faers_factory=lambda _task, _attempt: capability,
        )
        pending = SourceTaskState(task_id=task_id, source=SourceType.FAERS)
        running = SourceTaskState(
            task_id=task_id,
            source=SourceType.FAERS,
            status=SourceTaskStatus.RUNNING,
            required_operations=source_collection.plan_operations(pending, scope, attempt),
            attempts=1,
            active_attempt=attempt,
        )
        projected = source_collection.collect(running, scope, attempt)
        assert isinstance(projected, CollectedEvidenceResult)
        terminal = terminal_source_task(running, projected, run_id)
        source_collection.validate_terminal_task(terminal, scope)
        daily_records = DailyMedV2RecordStore(
            snapshots=store, repository=DailyMedV2Repository(repository)
        )
        reader = VerifiedSourceMaterialReader(
            repository=repository,
            provenance=VerifiedEvidenceProvenanceStore(snapshots=store, repository=repository),
            m1b_provenance=VerifiedM1BEvidenceProvenanceStore(
                snapshots=store, repository=repository
            ),
            dailymed_v2_provenance=DailyMedV2ProvenanceStore(
                snapshots=store, repository=repository, records=daily_records
            ),
            dailymed_v2_records=daily_records,
            pubmed_material=None,
            pubmed_catalog=None,
            faers_bridge_factory=lambda _task, _attempt: bridge,
        )
        assert len(reader.load(run_id=run_id, scope=scope, tasks=(terminal,))) == (
            1 if status == 200 else 0
        )
        assert calls == 1
        if status == 200:
            assert provenance.bucket_evidence[0].evidence_id.startswith("evidence:sha256:")
            provenance_store = VerifiedM1BEvidenceProvenanceStore(
                snapshots=store, repository=repository
            )
            projection = FaersAggregateExecutionProjection(
                run_id=run_id,
                scope_id=scope.scope_id,
                task_id=source_task_id(run_id, SourceType.FAERS),
                attempt_id=attempt_id,
                execution=first,
                bucket_evidence=provenance.bucket_evidence,
            )
            envelope = provenance_store.publish_faers(projection)[0]
            assert (
                provenance_store.load_verified_provenance(
                    run_id=envelope.run_id,
                    evidence_id=envelope.evidence_id,
                    source=envelope.source,
                    source_record_id=envelope.source_record_id,
                    source_version=envelope.source_version,
                    snapshot_id=envelope.snapshot_id,
                    content_hash=envelope.content_hash,
                )
                is not None
            )
        assert bridge.execute(query) == first
        assert calls == 1
        lifecycle = repository.get_m1b_acquisition_lifecycle(
            first.acquisition_outcome_ref.acquisition_id
        )
        assert lifecycle is not None and lifecycle.completed_at_utc == now
        if status == 200:
            with engine.begin() as connection:
                connection.execute(
                    m1b_faers_buckets.update()
                    .where(m1b_faers_buckets.c.run_id == run_id)
                    .values(report_count=8)
                )
            with pytest.raises(SnapshotIntegrityError, match="PostgreSQL bucket"):
                bridge.load_aggregate(execution=first)
            with engine.begin() as connection:
                connection.execute(
                    m1b_faers_buckets.update()
                    .where(m1b_faers_buckets.c.run_id == run_id)
                    .values(report_count=7)
                )
        intent_path = next((store.root / "journal").rglob("intent.json"))
        intent_path.write_bytes(b"{}")
        with pytest.raises((SnapshotIntegrityError, ValueError)):
            bridge.execute(query)
        assert calls == 1
        with engine.connect() as connection:
            artifact_ids = (
                *connection.execute(
                    sa.select(m1b_snapshot_artifacts.c.artifact_id).where(
                        m1b_snapshot_artifacts.c.run_id == run_id
                    )
                ).scalars(),
                first.result.manifest_id,
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                m3_evidence_provenance.delete().where(m3_evidence_provenance.c.run_id == run_id)
            )
            connection.execute(
                m1b_faers_buckets.delete().where(m1b_faers_buckets.c.run_id == run_id)
            )
            connection.execute(
                m1b_faers_queries.delete().where(m1b_faers_queries.c.run_id == run_id)
            )
            connection.execute(
                m1b_source_outcomes.delete().where(m1b_source_outcomes.c.run_id == run_id)
            )
            connection.execute(
                m1b_snapshot_artifacts.delete().where(m1b_snapshot_artifacts.c.run_id == run_id)
            )
            connection.execute(m1b_snapshots.delete().where(m1b_snapshots.c.run_id == run_id))
            connection.execute(m1b_acquisitions.delete().where(m1b_acquisitions.c.run_id == run_id))
            connection.execute(m1b_runs.delete().where(m1b_runs.c.run_id == run_id))
            connection.execute(
                m1b_artifacts.delete().where(m1b_artifacts.c.artifact_id.in_(artifact_ids))
            )
        repository.close()
        engine.dispose()


def test_faers_bridge_never_resends_unknown_started_attempt(tmp_path: Path) -> None:
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    identity = uuid4()
    run_id = f"run:{identity}"
    request_id = f"request:{identity}"
    attempt_id = source_task_attempt(source_task_id(run_id, SourceType.FAERS), 1).attempt_id
    scope = _scope(SourceType.FAERS)
    faers_request = _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    request = M1BResearchRequestV1(
        request_id=request_id,
        scope=scope,
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=(faers_request,),
    )
    factory_calls = 0

    def crash_after_intent() -> httpx.BaseTransport:
        nonlocal factory_calls
        factory_calls += 1
        raise RuntimeError("synthetic crash after durable START")

    now = datetime(2026, 9, 15, tzinfo=UTC)
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    bridge = FaersSourceExecutionBridge(
        run_id=run_id,
        scope=scope,
        request=request,
        task_id=source_task_id(run_id, SourceType.FAERS),
        attempt_id=attempt_id,
        clock=lambda: now,
        code_revision="b" * 40,
        transport_factory=crash_after_intent,
        store=SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000),
        repository=repository,
    )
    query = FaersAggregateQueryV1.create(faers_request)
    try:
        with pytest.raises(RuntimeError, match="synthetic crash"):
            bridge.execute(query)
        with pytest.raises(M1BSourceExecutionUnavailable, match="started_state_unknown"):
            bridge.execute(query)
        assert factory_calls == 1
    finally:
        with engine.begin() as connection:
            connection.execute(m1b_acquisitions.delete().where(m1b_acquisitions.c.run_id == run_id))
            connection.execute(m1b_runs.delete().where(m1b_runs.c.run_id == run_id))
        repository.close()
        engine.dispose()


def test_m1b_run_lifecycle_is_one_way_and_terminal_idempotent() -> None:
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    identity = uuid4()
    now = datetime(2026, 9, 15, tzinfo=UTC)
    running = M1BRunLifecycle(
        run_id=f"run:{identity}",
        request_id=f"request:{identity}",
        scope_id="scope:sha256:" + "7" * 64,
        status="running",
        created_at_utc=now,
        completed_at_utc=None,
    )
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    try:
        assert repository.begin_m1b_run(running) == (running, True)
        terminal = replace(running, status="completed", completed_at_utc=now)
        assert repository.finalize_m1b_run(terminal) == terminal
        assert repository.finalize_m1b_run(terminal) == terminal
        assert repository.begin_m1b_run(running) == (terminal, False)
        with pytest.raises(PersistenceConflict):
            repository.finalize_m1b_run(replace(terminal, status="degraded"))
    finally:
        with engine.begin() as connection:
            connection.execute(m1b_runs.delete().where(m1b_runs.c.run_id == running.run_id))
        repository.close()
        engine.dispose()
