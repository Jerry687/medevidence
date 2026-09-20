"""The local PubMed material gate reads an actual canonical PostgreSQL job."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from tests.unit.infrastructure.test_local_source_runtime import (
    PUBLICATION_VERSION,
    SEARCH_SNAPSHOT,
    SNAPSHOT,
    _scope,
)

from medevidence.domain import canonical_json, sha256_digest
from medevidence.infrastructure.evidence_provenance import VerifiedEvidenceProvenanceStore
from medevidence.infrastructure.local_research_catalog import LocalResearchCatalogAdapter
from medevidence.infrastructure.pubmed_material_store import (
    PubMedMaterialStoreError,
    SnapshotPubMedMaterialStore,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.persistence import PersistenceRepository, PersistenceSettings
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.research_jobs import ResearchJobRepository, m3_research_jobs
from medevidence.tools.ports import PubMedSearchProgressRecord
from medevidence.tools.pubmed import build_pubmed_query, query_identity


def test_pg_local_job_authority_rejects_foreign_and_unstarted_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None or "@127.0.0.1:55434/" not in url:
        pytest.skip("dedicated runtime PostgreSQL 55434 is required")
    command.upgrade(Config("alembic.ini"), "head")
    settings = PersistenceSettings(url)
    jobs = ResearchJobRepository(settings)
    repository = PersistenceRepository(settings)
    engine = sa.create_engine(url)
    scope = _scope()
    catalog = LocalResearchCatalogAdapter(scope).resolve(scope.scope_id)
    query = build_pubmed_query(scope, catalog)
    query_id = query_identity(scope, query)
    snapshot = SimpleNamespace(
        attempt={
            "run_id": "",
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
    search_snapshot = SimpleNamespace(
        attempt={
            "run_id": "",
            "operation": "search",
            "acquisition_ordinal": 0,
            "acquisition_intent_id": "acquisition-intent:sha256:" + "e" * 64,
        },
        snapshot={"source": "pubmed", "request_identity": query_id},
    )
    monkeypatch.setattr(
        PersistenceRepository,
        "get_snapshot",
        lambda _self, identity: search_snapshot if identity == SEARCH_SNAPSHOT else snapshot,
    )
    key = sha256_digest(str(uuid4()))
    try:
        row, created = jobs.create(
            idempotency_key=key,
            scope_id=scope.scope_id,
            scope_payload=scope.model_dump(mode="json"),
        )
        assert created
        run_id = row["run_id"]
        assert isinstance(run_id, str)
        snapshot.attempt["run_id"] = run_id
        search_snapshot.attempt["run_id"] = run_id
        search = PubMedSearchProgressRecord.create(
            run_id=run_id,
            scope_id=scope.scope_id,
            query=query,
            query_id=query_id,
            acquisition_intent_id=search_snapshot.attempt["acquisition_intent_id"],
            snapshot_id=SEARCH_SNAPSHOT,
            manifest_id=SEARCH_SNAPSHOT,
            pmids=("111",),
            search_source_outcome_id="source-operation-outcome:sha256:" + "f" * 64,
            valid_result_count=1,
        )
        monkeypatch.setattr(
            SnapshotStore,
            "read_pubmed_search_progress",
            lambda _self, _run: search.artifact_bytes(),
        )
        snapshots = SnapshotStore(tmp_path / "snapshots")
        material = SnapshotPubMedMaterialStore(
            snapshots=snapshots,
            repository=repository,
            provenance=VerifiedEvidenceProvenanceStore(snapshots=snapshots, repository=repository),
            local_jobs=jobs,
        )
        with pytest.raises(PubMedMaterialStoreError, match="unstarted"):
            material._verify_run_scope(
                run_id=run_id,
                scope=scope,
                catalog=catalog,
                snapshot_id=SNAPSHOT,
                publication_version_id=PUBLICATION_VERSION,
            )
        jobs.transition(run_id, expected="submitted", target="running")
        assert (
            material._verify_run_scope(
                run_id=run_id,
                scope=scope,
                catalog=catalog,
                snapshot_id=SNAPSHOT,
                publication_version_id=PUBLICATION_VERSION,
            )
            == "pubmed:111"
        )
        foreign = "run:00000000-0000-4000-8000-000000000001"
        with pytest.raises(PubMedMaterialStoreError, match="unavailable"):
            material._verify_run_scope(
                run_id=foreign,
                scope=scope,
                catalog=catalog,
                snapshot_id=SNAPSHOT,
                publication_version_id=PUBLICATION_VERSION,
            )
        altered_catalog = catalog.model_copy(update={"catalog_content_hash": "sha256:" + "f" * 64})
        with pytest.raises(PubMedMaterialStoreError, match="foreign"):
            material._verify_run_scope(
                run_id=run_id,
                scope=scope,
                catalog=altered_catalog,
                snapshot_id=SNAPSHOT,
                publication_version_id=PUBLICATION_VERSION,
            )
        assert row["scope_hash"] == sha256_digest(canonical_json(scope.model_dump(mode="json")))
    finally:
        with engine.begin() as connection:
            connection.execute(
                m3_research_jobs.delete().where(m3_research_jobs.c.idempotency_key == key)
            )
        engine.dispose()
        jobs.close()
        repository.close()
