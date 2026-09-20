"""Local source authority rejects foreign or unbound material before replay."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from medevidence.composition import build_local_source_runtime
from medevidence.domain import (
    ComparisonIntent,
    PlanningStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.infrastructure.cadec_material_runtime import CadecMaterialRuntime
from medevidence.infrastructure.dailymed_v2_source_execution import (
    DailyMedV2RunResult,
    DailyMedV2SourceExecutionBridge,
)
from medevidence.infrastructure.evidence_provenance import VerifiedEvidenceProvenanceStore
from medevidence.infrastructure.local_research_catalog import LocalResearchCatalogAdapter
from medevidence.infrastructure.local_source_policy import LocalSourceQueryPolicy
from medevidence.infrastructure.local_source_runtime import LocalDailyMedV2Capability
from medevidence.infrastructure.pubmed_material_store import (
    PubMedMaterialStoreError,
    SnapshotPubMedMaterialStore,
)
from medevidence.infrastructure.research_scope_safety import load_local_research_input_catalog
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore
from medevidence.orchestration.contracts import (
    CollectionFailureClassification,
    SourceTaskState,
    SourceTaskStatus,
    source_task_attempt,
    source_task_id,
)
from medevidence.persistence import PersistenceRepository
from medevidence.persistence.research_jobs import ResearchJobRepository
from medevidence.tools.ports import PubMedSearchProgressRecord
from medevidence.tools.pubmed import build_pubmed_query, query_identity

RUN = "run:12345678-1234-4234-9234-123456789abc"
SNAPSHOT = "sha256:" + "a" * 64
SEARCH_SNAPSHOT = "sha256:" + "b" * 64
PUBLICATION_VERSION = "publication-version:sha256:" + "d" * 64


def _scope() -> ResearchScope:
    catalog = load_local_research_input_catalog()
    return ResearchScope.create(
        drugs=(catalog.drugs_by_term["semaglutide"],),
        adverse_reactions=(catalog.reactions_by_term["nausea"],),
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


@pytest.mark.parametrize(
    "drift",
    (
        "none",
        "missing_job",
        "foreign_scope",
        "tampered_hash",
        "unstarted",
        "foreign_snapshot",
        "missing_search",
        "foreign_pmid",
    ),
)
def test_local_pubmed_material_requires_exact_job_and_acquisition(
    tmp_path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    scope = _scope()
    catalog = LocalResearchCatalogAdapter(scope, today=lambda: date(2026, 9, 18)).resolve(
        scope.scope_id
    )
    query = build_pubmed_query(scope, catalog)
    query_id = query_identity(scope, query)
    search = PubMedSearchProgressRecord.create(
        run_id=RUN,
        scope_id=scope.scope_id,
        query=query,
        query_id=query_id,
        acquisition_intent_id="acquisition-intent:sha256:" + "e" * 64,
        snapshot_id=SEARCH_SNAPSHOT,
        manifest_id=SEARCH_SNAPSHOT,
        pmids=("222",) if drift == "foreign_pmid" else ("111",),
        search_source_outcome_id="source-operation-outcome:sha256:" + "f" * 64,
        valid_result_count=1,
    )

    def read_search(_self: SnapshotStore, _run: str) -> bytes:
        if drift == "missing_search":
            raise SnapshotIntegrityError("missing synthetic search receipt")
        return search.artifact_bytes()

    monkeypatch.setattr(SnapshotStore, "read_pubmed_search_progress", read_search)
    payload = scope.model_dump(mode="json")
    job: dict[str, object] = {
        "run_id": RUN,
        "scope_id": scope.scope_id,
        "scope_payload": payload,
        "scope_hash": sha256_digest(canonical_json(payload)),
        "phase": "running",
    }
    if drift == "foreign_scope":
        job["scope_id"] = "scope:sha256:" + "b" * 64
    elif drift == "tampered_hash":
        job["scope_hash"] = "sha256:" + "c" * 64
    elif drift == "unstarted":
        job["phase"] = "submitted"
    snapshot = SimpleNamespace(
        attempt={
            "run_id": RUN,
            "manifest_id": SNAPSHOT,
            "acquisition_intent_id": "intent",
            "source": "pubmed",
            "operation": "fetch",
            "request_identity": "pubmed:111",
        },
        snapshot={
            "source": "pubmed",
            "request_identity": "pubmed:111",
            "acquisition_intent_id": "intent",
        },
        publications=({"publication_version_id": PUBLICATION_VERSION, "pmid": "111"},),
    )
    if drift == "foreign_snapshot":
        snapshot.attempt["run_id"] = "run:00000000-0000-4000-8000-000000000001"
    search_snapshot = SimpleNamespace(
        attempt={
            "run_id": RUN,
            "operation": "search",
            "acquisition_ordinal": 0,
            "acquisition_intent_id": search.acquisition_intent_id,
        },
        snapshot={"source": "pubmed", "request_identity": query_id},
    )
    monkeypatch.setattr(
        ResearchJobRepository, "load", lambda _self, _run: None if drift == "missing_job" else job
    )
    monkeypatch.setattr(
        PersistenceRepository,
        "get_snapshot",
        lambda _self, identity: search_snapshot if identity == SEARCH_SNAPSHOT else snapshot,
    )
    repository = cast(PersistenceRepository, object.__new__(PersistenceRepository))
    jobs = cast(ResearchJobRepository, object.__new__(ResearchJobRepository))
    snapshots = SnapshotStore(tmp_path)
    provenance = VerifiedEvidenceProvenanceStore(snapshots=snapshots, repository=repository)
    material = SnapshotPubMedMaterialStore(
        snapshots=snapshots,
        repository=repository,
        provenance=provenance,
        local_jobs=jobs,
    )
    if drift == "none":
        assert (
            material._verify_run_scope(
                run_id=RUN,
                scope=scope,
                catalog=catalog,
                snapshot_id=SNAPSHOT,
                publication_version_id=PUBLICATION_VERSION,
            )
            == "pubmed:111"
        )
    else:
        with pytest.raises(PubMedMaterialStoreError):
            material._verify_run_scope(
                run_id=RUN,
                scope=scope,
                catalog=catalog,
                snapshot_id=SNAPSHOT,
                publication_version_id=PUBLICATION_VERSION,
            )


def test_dailymed_task_material_cap_fails_closed_before_terminal_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_local_research_input_catalog()
    scope = ResearchScope.create(
        drugs=(catalog.drugs_by_term["semaglutide"],),
        adverse_reactions=(catalog.reactions_by_term["nausea"],),
        date_range=None,
        selected_sources=(SourceType.DAILYMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    request = LocalSourceQueryPolicy(scope, datetime(2026, 9, 18, tzinfo=UTC)).build_request(
        "request:12345678-1234-4234-9234-123456789abc"
    )
    task_id = source_task_id(RUN, SourceType.DAILYMED)
    attempt = source_task_attempt(task_id, 1)
    bridge = object.__new__(DailyMedV2SourceExecutionBridge)
    monkeypatch.setattr(
        DailyMedV2SourceExecutionBridge,
        "execute_current",
        lambda _self: DailyMedV2RunResult(
            groups=(),
            packaging=(),
            decisions=(),
            selected_spl=(),
            evidence_chunks=(),
            review_reason_codes=("task_chunk_cap_exceeded",),
        ),
    )
    capability = LocalDailyMedV2Capability(
        run_id=RUN,
        request=request,
        records=cast(object, object()),  # no record read is permitted after cap admission
        bridge_factory=lambda _task, _attempt: bridge,
    )
    pending = SourceTaskState(task_id=task_id, source=SourceType.DAILYMED)
    operations = capability.plan_operations(pending, scope, attempt)
    running = SourceTaskState(
        task_id=task_id,
        source=SourceType.DAILYMED,
        status=SourceTaskStatus.RUNNING,
        required_operations=operations,
        attempts=1,
        active_attempt=attempt,
    )
    failure = capability.collect(running, scope, attempt)
    assert failure.reason_code == "dailymed_material_cap_exceeded"
    assert failure.classification is CollectionFailureClassification.PERMANENT
    assert not hasattr(failure, "terminal_outcome_ref")


@pytest.mark.parametrize("configured", (False, True))
def test_local_runtime_selects_only_configured_cadec_assets(
    tmp_path: Path, configured: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = load_local_research_input_catalog()
    scope = ResearchScope.create(
        drugs=(catalog.drugs_by_term["semaglutide"],),
        adverse_reactions=(catalog.reactions_by_term["nausea"],),
        date_range=None,
        selected_sources=(SourceType.CADEC,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    archive = tmp_path / "archive.zip"
    manifest = tmp_path / "manifest.json"
    if configured:
        archive.write_bytes(b"synthetic fixture only")
        manifest.write_bytes(b"{}")
    bundle = build_local_source_runtime(
        run_id=RUN,
        scope=scope,
        run_created_at_utc=datetime(2026, 9, 18, tzinfo=UTC),
        code_revision="a" * 40,
        snapshots=SnapshotStore(tmp_path / "snapshots"),
        repository=cast(PersistenceRepository, object.__new__(PersistenceRepository)),
        jobs=cast(ResearchJobRepository, object.__new__(ResearchJobRepository)),
        transport_factory=lambda: (_ for _ in ()).throw(AssertionError("source transport opened")),
        attempt_id_factory=lambda: "attempt:12345678-1234-4234-9234-123456789abc",
        utc_now=lambda: datetime(2026, 9, 18, tzinfo=UTC),
        cadec_archive_path=archive if configured else None,
        cadec_manifest_path=manifest if configured else None,
    )
    try:
        row = bundle.planning._plan[0]
        assert row.source is SourceType.CADEC
        assert row.planning_status is (
            PlanningStatus.SELECTED if configured else PlanningStatus.SKIPPED_BY_POLICY
        )
        if configured:
            assert row.reason is None
            assert type(bundle.evidence_collection._base) is CadecMaterialRuntime
            assert bundle.provenance_store._cadec is bundle.evidence_collection._base
            marker = object()
            monkeypatch.setattr(
                CadecMaterialRuntime,
                "load_verified_provenance",
                lambda _self, **_keys: marker,
            )
            assert (
                bundle.provenance_store.load_verified_provenance(
                    run_id=RUN,
                    evidence_id="evidence:sha256:" + "a" * 64,
                    source=SourceType.CADEC,
                    source_record_id="synthetic-record",
                    source_version="synthetic-version",
                    snapshot_id="sha256:" + "b" * 64,
                    content_hash="sha256:" + "c" * 64,
                )
                is marker
            )
        else:
            assert row.reason is not None
            assert row.reason.startswith("local_cadec_asset_unavailable:")
    finally:
        bundle.close()
