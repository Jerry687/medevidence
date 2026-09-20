"""Disposable PostgreSQL test for exact DailyMed V2 metadata records."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
    derive_identity,
)
from medevidence.domain.dailymed_enrichment import (
    DailyMedPackagingExecutionV2,
    DailyMedPackagingProductV2,
    DailyMedRawParentV2,
)
from medevidence.domain.dailymed_v2_execution import DailyMedV2PackagingResult
from medevidence.infrastructure.dailymed_v2_record_store import DailyMedV2RecordStore
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.persistence import PersistenceRepository, PersistenceSettings
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.dailymed_v2 import (
    DailyMedV2RecordInput,
    DailyMedV2Repository,
)
from medevidence.persistence.models import (
    m1b_acquisitions,
    m1b_artifacts,
    m1b_runs,
    m1b_snapshots,
    m3_dailymed_v2_records,
)
from medevidence.persistence.repositories import (
    M1BAcquisitionLifecycle,
    M1BRunLifecycle,
    PersistenceConflict,
    PersistenceIntegrityError,
)


def test_packaging_operation_and_canonical_record_survive_reopen(tmp_path: Path) -> None:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    command.upgrade(Config("alembic.ini"), "head")
    identity = uuid4()
    run_id = f"run:{identity}"
    acquisition_id = f"acquisition:dailymed-v2:{identity}"
    query_id = derive_identity(
        "dailymed-packaging-query-v2",
        {
            "summary_id": "summary:synthetic",
            "setid": "11111111-1111-4111-8111-111111111111",
            "spl_version": "2",
        },
    )
    manifest_id = "sha256:" + identity.hex * 2
    now = datetime(2026, 9, 16, tzinfo=UTC)
    repository = PersistenceRepository(PersistenceSettings(url))
    store = DailyMedV2Repository(repository)
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    typed_store = DailyMedV2RecordStore(snapshots=snapshots, repository=store)
    engine = sa.create_engine(url)
    execution = DailyMedPackagingExecutionV2(
        parent=DailyMedRawParentV2(
            kind="packaging_json",
            run_id=run_id,
            attempt_id=f"source-task-attempt:{identity}",
            acquisition_id=acquisition_id,
            acquisition_ordinal=1,
            acquisition_intent_id="acquisition-intent:sha256:" + "b" * 64,
            query_id=query_id,
            snapshot_id=f"snapshot:dailymed-v2:{identity}",
            manifest_id=manifest_id,
            member_ordinal=0,
            link_id=f"dailymed-v2-link:{identity}",
            raw_artifact_id="sha256:" + "c" * 64,
            raw_content_hash="sha256:" + "c" * 64,
            byte_size=10,
        ),
        products=(
            DailyMedPackagingProductV2(
                product_name="Synthetic product",
                ingredients=("Synthetic ingredient",),
                strengths=("1 unit",),
                ndcs=("0001-0001",),
            ),
        ),
    )
    payload = DailyMedV2PackagingResult(
        summary_id="summary:synthetic",
        discovery_query_id="discovery-query:synthetic",
        packaging_query_id=query_id,
        setid="11111111-1111-4111-8111-111111111111",
        expected_current_spl_version="2",
        source_outcome=SourceOutcome(
            source=SourceType.DAILYMED,
            query_id=query_id,
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES,
            configured_bounds=ExecutionBounds(
                max_query_characters=512,
                max_pages=5,
                max_records=100,
                max_payload_bytes=5_242_880,
                max_total_seconds=30,
            ),
            valid_result_count=1,
            pages_completed=1,
            truncated=False,
        ),
        execution=execution,
    )
    record = DailyMedV2RecordInput(
        record_kind="packaging",
        run_id=run_id,
        scope_id="scope:sha256:" + "a" * 64,
        task_id=f"source-task:{identity}:dailymed",
        attempt_id=f"source-task-attempt:{identity}",
        query_id=query_id,
        acquisition_id=acquisition_id,
        acquisition_intent_id="acquisition-intent:sha256:" + "b" * 64,
        snapshot_id=f"snapshot:dailymed-v2:{identity}",
        manifest_id=manifest_id,
        item_ordinal=0,
        payload_bytes=canonical_json(payload).encode(),
        created_at_utc=now,
    )
    try:
        repository.begin_m1b_run(
            M1BRunLifecycle(run_id, f"request:{identity}", record.scope_id, "running", now, None)
        )
        repository.begin_m1b_acquisition(
            M1BAcquisitionLifecycle(
                acquisition_intent_id=record.acquisition_intent_id,
                acquisition_ordinal=1,
                attempt_id=record.attempt_id,
                run_id=run_id,
                acquisition_id=acquisition_id,
                source="dailymed",
                operation="packaging",
                request_identity=query_id,
                query_id=query_id,
                execution_profile_id="DAILYMED_M1B_CONSTRAINED_V1",
                started_at_utc=now,
                completed_at_utc=None,
                schema_version="m1b.acquisition.v1",
            )
        )
        repository.insert_or_verify_m1b_artifact(
            {
                "artifact_id": manifest_id,
                "artifact_kind": "dailymed_v2_packaging_manifest",
                "source_partition": "dailymed",
                "content_hash": manifest_id,
                "byte_size": 1,
                "media_type": "application/json",
                "relative_storage_label": f"dailymed/v2/manifests/{identity.hex}.json",
                "schema_version": "m3.dailymed-v2-snapshot.v1",
                "created_at_utc": now,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
            }
        )
        repository.insert_or_verify_m1b(
            "m1b_snapshots",
            {
                "query_id": query_id,
                "acquisition_intent_id": record.acquisition_intent_id,
                "acquisition_ordinal": 1,
                "attempt_id": record.attempt_id,
                "run_id": run_id,
                "snapshot_id": record.snapshot_id,
                "acquisition_id": acquisition_id,
                "source": "dailymed",
                "manifest_artifact_id": manifest_id,
                "retrieved_at_utc": now,
                "connector_version": "m1b-dm-002",
                "schema_version": "m3.dailymed-v2.snapshot.v1",
            },
        )
        assert typed_store.save(record, payload).payload == payload
        assert store.save(record) == record
        assert DailyMedV2Repository(repository).load(record.record_id) == record
        assert (
            DailyMedV2RecordStore(snapshots=snapshots, repository=store)
            .load(record.record_id)
            .payload
            == payload
        )
        with pytest.raises(PersistenceConflict):
            store.save(
                DailyMedV2RecordInput(
                    **{
                        **{name: getattr(record, name) for name in record.__dataclass_fields__},
                        "payload_bytes": canonical_json(
                            {"kind": "packaging", "value": "foreign"}
                        ).encode(),
                    }
                )
            )
        with engine.begin() as connection:
            connection.execute(
                m3_dailymed_v2_records.update()
                .where(m3_dailymed_v2_records.c.record_id == record.record_id)
                .values(payload_json={"kind": "packaging", "value": "tampered"})
            )
        with pytest.raises(PersistenceIntegrityError):
            store.load(record.record_id)
    finally:
        with engine.begin() as connection:
            connection.execute(
                m3_dailymed_v2_records.delete().where(m3_dailymed_v2_records.c.run_id == run_id)
            )
            connection.execute(m1b_snapshots.delete().where(m1b_snapshots.c.run_id == run_id))
            connection.execute(m1b_acquisitions.delete().where(m1b_acquisitions.c.run_id == run_id))
            connection.execute(m1b_runs.delete().where(m1b_runs.c.run_id == run_id))
            connection.execute(
                m1b_artifacts.delete().where(m1b_artifacts.c.artifact_id == manifest_id)
            )
        repository.close()
        engine.dispose()
