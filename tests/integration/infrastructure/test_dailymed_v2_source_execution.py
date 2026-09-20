"""Mock-transport current-label execution with real immutable PostgreSQL rows."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from tests.unit.orchestration.test_dailymed_faers_capability import _scope

from medevidence.connectors.dailymed import (
    DailyMedOperation,
    DailyMedRequest,
    build_dailymed_request,
)
from medevidence.connectors.dailymed.parsing import parse_spl_document
from medevidence.domain import (
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    M1BResearchRequestV1,
    SourceType,
)
from medevidence.infrastructure.dailymed_v2_provenance import DailyMedV2ProvenanceStore
from medevidence.infrastructure.dailymed_v2_record_store import DailyMedV2RecordStore
from medevidence.infrastructure.dailymed_v2_source_execution import (
    DailyMedV2SourceExecutionBridge,
)
from medevidence.infrastructure.evidence_provenance import EvidenceProvenanceIntegrityError
from medevidence.infrastructure.local_source_runtime import LocalDailyMedV2Capability
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    SourceTaskState,
    SourceTaskStatus,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.source_capabilities import terminal_source_task
from medevidence.persistence import PersistenceRepository, PersistenceSettings
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.dailymed_v2 import DailyMedV2Repository
from medevidence.persistence.models import (
    m1b_acquisitions,
    m1b_artifacts,
    m1b_runs,
    m1b_snapshot_artifacts,
    m1b_snapshots,
    m1b_source_outcomes,
    m3_dailymed_v2_members,
    m3_dailymed_v2_records,
    m3_evidence_provenance,
)
from medevidence.tools.contracts import DailyMedDiscoveryRequest

SETID = "11111111-1111-1111-1111-111111111111"


def _url() -> str:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    return value


class _Native:
    def resolve(self, _request: DailyMedDiscoveryRequest) -> DailyMedRequest:
        return build_dailymed_request(
            DailyMedOperation.DISCOVERY,
            query={"setid": SETID, "pagesize": 100},
        )


class _NativePage1(_Native):
    def resolve(self, _request: DailyMedDiscoveryRequest) -> DailyMedRequest:
        return build_dailymed_request(
            DailyMedOperation.DISCOVERY,
            query={"setid": SETID, "pagesize": 1},
        )


def _discovery() -> bytes:
    return json.dumps(
        {
            "metadata": {
                "current_page": "1",
                "pagesize": "100",
                "total_elements": "1",
            },
            "data": [
                {
                    "setid": SETID,
                    "spl_version": "3",
                    "title": "SYNTHETIC PRODUCT TABLET [TEST]",
                    "published_date": "Nov 01, 2013",
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _partial_discovery() -> bytes:
    value = json.loads(_discovery())
    value["metadata"]["pagesize"] = "1"
    value["metadata"]["total_elements"] = "2"
    return json.dumps(value, separators=(",", ":")).encode()


def _packaging(*, page: int = 1, next_page: int | None = None) -> bytes:
    return json.dumps(
        {
            "metadata": {
                "current_page": str(page),
                "next_page": "null" if next_page is None else str(next_page),
            },
            "data": {
                "setid": SETID,
                "spl_version": "3",
                "title": "SYNTHETIC PRODUCT",
                "published_date": "Nov 01, 2013",
                "products": [
                    {
                        "product_code": "0001",
                        "product_name": "SYNTHETIC PRODUCT",
                        "product_name_generic": "synthetic generic",
                        "active_ingredients": [
                            {"name": "Synthetic ingredient", "strength": "1 mg"}
                        ],
                        "packaging": [{"ndc": "0001-0001", "package_descriptions": []}],
                        "parts": {},
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode()


@pytest.mark.parametrize(
    "case", ("normal", "duplicate", "multi_page", "partial_discovery", "partial_packaging")
)
def test_current_label_discovery_enrichment_fetch_and_restart(tmp_path: Path, case: str) -> None:
    duplicate_retry_body = case == "duplicate"
    multi_page = case == "multi_page"
    url = _url()
    command.upgrade(Config("alembic.ini"), "head")
    identity = uuid4()
    run_id = f"run:{identity}"
    task_id = source_task_id(run_id, SourceType.DAILYMED)
    attempt_id = source_task_attempt(task_id, 1).attempt_id
    scope = _scope(SourceType.DAILYMED)
    request = M1BResearchRequestV1(
        request_id=f"request:{identity}",
        scope=scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(
            DailyMedSelectionRequestV1(
                drug_concept_id=scope.drugs[0].concept_id,
                requested_section_codes=("34084-4",),
                selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
            ),
        ),
    )
    spl = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
    calls: list[str] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        calls.append(sent.url.path)
        if sent.url.path.endswith("/spls.json"):
            if case == "partial_discovery":
                if sent.url.params.get("page") == "2":
                    return httpx.Response(503, content=b"unavailable")
                return httpx.Response(
                    200,
                    content=_partial_discovery(),
                    headers={"Content-Type": "application/json"},
                )
            if duplicate_retry_body and sum(item.endswith("/spls.json") for item in calls) == 1:
                return httpx.Response(
                    503, content=_discovery(), headers={"Content-Type": "application/json"}
                )
            return httpx.Response(
                200, content=_discovery(), headers={"Content-Type": "application/json"}
            )
        if sent.url.path.endswith(f"/{SETID}/packaging.json"):
            page = int(sent.url.params.get("page", "1"))
            if case == "partial_packaging" and page == 2:
                return httpx.Response(503, content=b"unavailable")
            return httpx.Response(
                200,
                content=_packaging(
                    page=page,
                    next_page=(
                        2 if case in ("multi_page", "partial_packaging") and page == 1 else None
                    ),
                ),
                headers={"Content-Type": "application/json"},
            )
        if sent.url.path.endswith(f"/{SETID}.xml"):
            return httpx.Response(200, content=spl, headers={"Content-Type": "application/xml"})
        raise AssertionError("unexpected DailyMed URL")

    now = datetime(2026, 9, 16, tzinfo=UTC)
    repository = PersistenceRepository(PersistenceSettings(url))
    engine = sa.create_engine(url)
    snapshots = SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _: 20_000_000_000,
        dailymed_spl_validator=lambda body, setid, version: parse_spl_document(
            body, expected_setid=setid, expected_spl_version=version
        ),
    )

    def bridge() -> DailyMedV2SourceExecutionBridge:
        return DailyMedV2SourceExecutionBridge(
            run_id=run_id,
            scope=scope,
            request=request,
            task_id=task_id,
            attempt_id=attempt_id,
            clock=lambda: now,
            code_revision="a" * 40,
            native_requests=_NativePage1() if case == "partial_discovery" else _Native(),
            transport_factory=lambda: httpx.MockTransport(handler),
            snapshots=snapshots,
            repository=repository,
        )

    artifact_ids: tuple[str, ...] = ()
    try:
        first = bridge().execute_current()
        attempt = source_task_attempt(task_id, 1)
        capability = LocalDailyMedV2Capability(
            run_id=run_id,
            request=request,
            records=DailyMedV2RecordStore(
                snapshots=snapshots, repository=DailyMedV2Repository(repository)
            ),
            bridge_factory=lambda _task, _attempt: bridge(),
        )
        pending = SourceTaskState(task_id=task_id, source=SourceType.DAILYMED)
        running = SourceTaskState(
            task_id=task_id,
            source=SourceType.DAILYMED,
            status=SourceTaskStatus.RUNNING,
            required_operations=capability.plan_operations(pending, scope, attempt),
            attempts=1,
            active_attempt=attempt,
        )
        projected = capability.collect(running, scope, attempt)
        assert isinstance(projected, CollectedEvidenceResult)
        terminal = terminal_source_task(running, projected, run_id)
        capability.validate_terminal_task(terminal, scope)
        expected_calls = 4 if case in ("duplicate", "partial_packaging") else 3
        assert len(calls) == expected_calls
        assert len(first.groups) == len(first.decisions) == 1
        if case in ("partial_discovery", "partial_packaging"):
            partial = (
                first.groups[0].outcome
                if case == "partial_discovery"
                else first.packaging[0].source_outcome
            )
            assert partial.execution_status.value == "failed"
            assert partial.coverage_status.value == "partial"
            assert partial.result_status.value == "matches"
            assert partial.valid_result_count == partial.pages_completed == 1
            assert len(first.groups[0].summaries) == 1
            assert first.decisions[0].status.value == "review_required"
            assert first.selected_spl == first.evidence_chunks == ()
            assert bridge().execute_current() == first
            assert len(calls) == expected_calls
            with engine.connect() as connection:
                artifact_ids = (
                    *connection.execute(
                        sa.select(m3_dailymed_v2_members.c.artifact_id).where(
                            m3_dailymed_v2_members.c.run_id == run_id
                        )
                    ).scalars(),
                    *connection.execute(
                        sa.select(m1b_snapshots.c.manifest_artifact_id).where(
                            m1b_snapshots.c.run_id == run_id
                        )
                    ).scalars(),
                )
            return
        assert len(first.packaging) == 1
        if multi_page:
            assert first.packaging[0].source_outcome.pages_completed == 2
            assert first.packaging[0].source_outcome.coverage_status.value == "complete"
            assert first.packaging[0].reason.value == "enrichment_pagination_unsupported"
            assert first.decisions[0].status.value == "review_required"
            assert first.selected_spl == first.evidence_chunks == ()
            assert bridge().execute_current() == first
            assert len(calls) == expected_calls
            with engine.connect() as connection:
                artifact_ids = (
                    *connection.execute(
                        sa.select(m3_dailymed_v2_members.c.artifact_id).where(
                            m3_dailymed_v2_members.c.run_id == run_id
                        )
                    ).scalars(),
                    *connection.execute(
                        sa.select(m1b_snapshots.c.manifest_artifact_id).where(
                            m1b_snapshots.c.run_id == run_id
                        )
                    ).scalars(),
                )
            return
        assert first.decisions[0].status.value == "selected"
        assert first.packaging[0].execution is not None
        assert first.packaging[0].execution.products[0].ingredients == ("Synthetic ingredient",)
        assert len(first.selected_spl) == 1
        assert first.evidence_chunks
        proofs = DailyMedV2ProvenanceStore(
            snapshots=snapshots,
            repository=repository,
            records=DailyMedV2RecordStore(
                snapshots=snapshots, repository=DailyMedV2Repository(repository)
            ),
        )
        chunk = first.evidence_chunks[0]
        assert (
            proofs.load_verified_material(
                run_id=run_id,
                evidence_id=chunk.evidence_id,
                source_record_id=chunk.source_record_id,
                source_version=chunk.source_version,
                snapshot_id=chunk.snapshot_id,
                content_hash=chunk.chunk_hash,
            ).chunk
            == chunk
        )
        digest = chunk.chunk_hash.removeprefix("sha256:")
        normalized = (
            snapshots.root
            / "dailymed"
            / "normalized"
            / "sections"
            / "sha256"
            / digest[:2]
            / f"{digest}.txt"
        )
        original = normalized.read_bytes()
        normalized.write_bytes(b"X" * len(original))
        with pytest.raises(EvidenceProvenanceIntegrityError):
            proofs.load_verified_material(
                run_id=run_id,
                evidence_id=chunk.evidence_id,
                source_record_id=chunk.source_record_id,
                source_version=chunk.source_version,
                snapshot_id=chunk.snapshot_id,
                content_hash=chunk.chunk_hash,
            )
        normalized.write_bytes(original)
        selected_snapshot_id = first.selected_spl[0].fetch_snapshot_id
        with engine.connect() as connection:
            selected_member = connection.execute(
                sa.select(
                    m3_dailymed_v2_members.c.acquisition_id,
                    m3_dailymed_v2_members.c.ordinal,
                    m3_dailymed_v2_members.c.http_status,
                ).where(
                    m3_dailymed_v2_members.c.run_id == run_id,
                    m3_dailymed_v2_members.c.snapshot_id == selected_snapshot_id,
                )
            ).one()
        with engine.begin() as connection:
            connection.execute(
                m3_dailymed_v2_members.update()
                .where(
                    m3_dailymed_v2_members.c.acquisition_id == selected_member.acquisition_id,
                    m3_dailymed_v2_members.c.ordinal == selected_member.ordinal,
                )
                .values(http_status=201)
            )
        with pytest.raises(EvidenceProvenanceIntegrityError):
            proofs.load_verified_material(
                run_id=run_id,
                evidence_id=chunk.evidence_id,
                source_record_id=chunk.source_record_id,
                source_version=chunk.source_version,
                snapshot_id=chunk.snapshot_id,
                content_hash=chunk.chunk_hash,
            )
        with engine.begin() as connection:
            connection.execute(
                m3_dailymed_v2_members.update()
                .where(
                    m3_dailymed_v2_members.c.acquisition_id == selected_member.acquisition_id,
                    m3_dailymed_v2_members.c.ordinal == selected_member.ordinal,
                )
                .values(http_status=selected_member.http_status)
            )
            connection.execute(
                m3_evidence_provenance.delete().where(
                    m3_evidence_provenance.c.run_id == run_id,
                    m3_evidence_provenance.c.evidence_id == chunk.evidence_id,
                )
            )
        assert bridge().execute_current() == first
        assert (
            proofs.load_verified_material(
                run_id=run_id,
                evidence_id=chunk.evidence_id,
                source_record_id=chunk.source_record_id,
                source_version=chunk.source_version,
                snapshot_id=chunk.snapshot_id,
                content_hash=chunk.chunk_hash,
            )
            is not None
        )
        assert len(calls) == expected_calls
        if duplicate_retry_body:
            discovery_acquisition_id = first.groups[0].summaries[0].parent.acquisition_id
            with engine.connect() as connection:
                rows = connection.execute(
                    sa.select(
                        m3_dailymed_v2_members.c.ordinal,
                        m3_dailymed_v2_members.c.artifact_id,
                        m3_dailymed_v2_members.c.http_status,
                    )
                    .where(m3_dailymed_v2_members.c.acquisition_id == discovery_acquisition_id)
                    .order_by(m3_dailymed_v2_members.c.ordinal)
                ).all()
            assert len(rows) == 2
            assert rows[0].artifact_id == rows[1].artifact_id
            assert tuple(row.http_status for row in rows) == (503, 200)
            with engine.begin() as connection:
                connection.execute(
                    m3_dailymed_v2_members.update()
                    .where(
                        m3_dailymed_v2_members.c.acquisition_id == discovery_acquisition_id,
                        m3_dailymed_v2_members.c.ordinal == 1,
                    )
                    .values(ordinal=3)
                )
            with pytest.raises(SnapshotIntegrityError, match="ordered member"):
                bridge().execute_current()
            assert len(calls) == expected_calls
            with engine.begin() as connection:
                connection.execute(
                    m3_dailymed_v2_members.update()
                    .where(
                        m3_dailymed_v2_members.c.acquisition_id == discovery_acquisition_id,
                        m3_dailymed_v2_members.c.ordinal == 3,
                    )
                    .values(ordinal=1)
                )
        with engine.connect() as connection:
            artifact_ids = (
                *connection.execute(
                    sa.select(m3_dailymed_v2_members.c.artifact_id).where(
                        m3_dailymed_v2_members.c.run_id == run_id
                    )
                ).scalars(),
                *connection.execute(
                    sa.select(m1b_snapshots.c.manifest_artifact_id).where(
                        m1b_snapshots.c.run_id == run_id
                    )
                ).scalars(),
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                m3_evidence_provenance.delete().where(m3_evidence_provenance.c.run_id == run_id)
            )
            connection.execute(
                m3_dailymed_v2_records.delete().where(m3_dailymed_v2_records.c.run_id == run_id)
            )
            connection.execute(
                m3_dailymed_v2_members.delete().where(m3_dailymed_v2_members.c.run_id == run_id)
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
