"""PostgreSQL run, snapshot, and anchor readback for PubMed material."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from tests.integration.persistence.test_snapshot_metadata import (
    _complete_acquisition_registration,
    _run_report_values,
)
from tests.unit.infrastructure.test_pubmed_material_store import _fixture

from medevidence.domain import ResearchScope, canonical_json
from medevidence.infrastructure.evidence_provenance import VerifiedEvidenceProvenanceStore
from medevidence.infrastructure.pubmed_material_store import SnapshotPubMedMaterialStore
from medevidence.ingestion.artifacts import SnapshotManifest
from medevidence.persistence import (
    AcquisitionRegistration,
    ArtifactLineageRow,
    ArtifactRow,
    PersistenceRepository,
    PersistenceSettings,
    ResearchReportRow,
    ResearchRunAttemptRow,
    ResearchRunRow,
    RunReportRegistration,
    SourceSnapshotPublicationRow,
    SourceSnapshotRow,
    ValidatedAcquisitionEnvelope,
    ValidatedArtifactLink,
    ValidatedManifest,
    ValidatedManifestFile,
)
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.repositories import SnapshotMetadata
from medevidence.tools.contracts import ResolvedConceptCatalog
from medevidence.tools.pubmed import build_pubmed_query


def _lineage(parent: ArtifactRow, child: ArtifactRow, kind: str) -> ArtifactLineageRow:
    return ArtifactLineageRow(
        parent_artifact_id=parent["artifact_id"],
        parent_artifact_kind=parent["artifact_kind"],
        parent_source_partition=parent["source_partition"],
        parent_content_hash=parent["content_hash"],
        child_artifact_id=child["artifact_id"],
        child_artifact_kind=child["artifact_kind"],
        child_source_partition=child["source_partition"],
        child_content_hash=child["content_hash"],
        lineage_type=kind,
        lineage_ordinal=0,
        schema_version="1.0",
    )


def _register_source_metadata(
    repository: PersistenceRepository,
    *,
    run_id: str,
    source_metadata: SnapshotMetadata,
    manifest: SnapshotManifest,
    manifest_path: str,
    label: str,
    scope: ResearchScope,
    catalog: ResolvedConceptCatalog,
) -> None:
    """Write the same immutable parents consumed by material replay through repository APIs."""
    metadata = source_metadata
    search = _complete_acquisition_registration(f"{label}:search")
    search_attempt = cast(ResearchRunAttemptRow, {**search.attempt, "run_id": run_id})
    search = replace(
        search,
        attempt=search_attempt,
        envelope=replace(search.envelope, attempt=search_attempt),
    )
    repository.register_acquisition(search)

    scaffold = _complete_acquisition_registration(f"{label}:fetch")
    manifest_file = manifest.files[0]
    manifest_artifact = cast(
        ArtifactRow,
        {
            **scaffold.artifacts[0],
            "artifact_id": manifest.manifest_id,
            "content_hash": manifest.manifest_id,
            "byte_size": len(manifest.canonical_bytes()),
            "relative_storage_path": manifest_path,
        },
    )
    raw_artifact = cast(
        ArtifactRow,
        {
            **scaffold.artifacts[1],
            "artifact_id": manifest_file.artifact_id,
            "content_hash": manifest_file.artifact_id,
            "byte_size": manifest_file.byte_size,
            "relative_storage_path": manifest_file.relative_path,
        },
    )
    publication_row = metadata.publications[0]
    publication_artifact = cast(
        ArtifactRow,
        {
            **scaffold.artifacts[1],
            "artifact_id": publication_row["content_hash"],
            "artifact_kind": "publication_record",
            "content_hash": publication_row["content_hash"],
            "byte_size": len(canonical_json(publication_row["version_payload"]).encode("utf-8")),
            "media_type": "application/json",
            "relative_storage_path": (
                "pubmed/publications/sha256/"
                f"{publication_row['content_hash'][7:9]}/"
                f"{publication_row['content_hash'][7:]}.json"
            ),
        },
    )
    envelope_artifact = scaffold.artifacts[2]
    snapshot = cast(
        SourceSnapshotRow,
        {
            **scaffold.snapshot,
            **metadata.snapshot,
            "attempts_used": manifest.attempts_used,
            "connector_name": manifest.connector_name,
            "connector_version": manifest.connector_version,
            "manifest_schema_version": manifest.manifest_schema_version,
            "source_record_schema_version": manifest.source_record_schema_version,
            "code_revision": manifest.code_revision,
            "retention_policy_id": manifest.retention_policy_id,
            "manifest_artifact_kind": "snapshot_manifest",
            "manifest_source_partition": "pubmed",
        },
    )
    attempt = cast(
        ResearchRunAttemptRow,
        {
            **scaffold.attempt,
            "run_id": run_id,
            "acquisition_ordinal": 1,
            "acquisition_intent_id": manifest.acquisition_intent_id,
            "operation": "fetch",
            "intent_created_at_utc": manifest.started_at_utc,
            "request_identity": manifest.request_identity,
            "started_at_utc": manifest.started_at_utc,
            "completed_at_utc": manifest.completed_at_utc,
            "execution_status": manifest.execution_status.value,
            "coverage_status": manifest.coverage_status.value,
            "result_status": manifest.result_status.value,
            "valid_result_count": manifest.record_count,
            "pages_completed": manifest.pages_completed,
            "attempts_used": manifest.attempts_used,
            "truncated": manifest.truncated,
            "warning_codes": list(manifest.warning_codes),
            "manifest_id": manifest.manifest_id,
        },
    )
    link = ValidatedArtifactLink(
        link_id=manifest_file.link_id,
        acquisition_intent_id=manifest.acquisition_intent_id,
        ordinal=manifest_file.ordinal,
        artifact_id=manifest_file.artifact_id,
        artifact_kind="pubmed_http_response",
        media_type=manifest_file.media_type,
        content_encoding=manifest_file.content_encoding,
        http_status=manifest_file.http_status,
        byte_size=manifest_file.byte_size,
        body_complete=manifest_file.body_complete,
        termination_reason=manifest_file.termination_reason,
        observed_at_utc=manifest.completed_at_utc,
        schema_version="1.0",
    )
    validated = ValidatedManifest(
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
        files=(
            ValidatedManifestFile(
                ordinal=manifest_file.ordinal,
                link_id=manifest_file.link_id,
                artifact_id=manifest_file.artifact_id,
                relative_path=manifest_file.relative_path,
                byte_size=manifest_file.byte_size,
                media_type=manifest_file.media_type,
                content_encoding=manifest_file.content_encoding,
                http_status=manifest_file.http_status,
                body_complete=manifest_file.body_complete,
                termination_reason=manifest_file.termination_reason,
            ),
        ),
        connector_name=manifest.connector_name,
        connector_version=manifest.connector_version,
        source_record_schema_version=manifest.source_record_schema_version,
        code_revision=manifest.code_revision,
    )
    files, memberships = PersistenceRepository._expected_file_rows(validated, (link,), snapshot)
    publication_membership = cast(
        SourceSnapshotPublicationRow,
        {
            **metadata.publication_memberships[0],
            "snapshot_id": manifest.manifest_id,
            "publication_ordinal": 0,
            "source": "pubmed",
        },
    )
    lineage = (
        _lineage(manifest_artifact, raw_artifact, "manifest_to_raw_response"),
        _lineage(publication_artifact, manifest_artifact, "publication_to_manifest"),
    )
    fetch = AcquisitionRegistration(
        artifacts=(manifest_artifact, raw_artifact, envelope_artifact, publication_artifact),
        snapshot=snapshot,
        files=files,
        memberships=memberships,
        warnings=(),
        publications=(publication_row,),
        publication_memberships=(publication_membership,),
        lineage=lineage,
        attempt=attempt,
        manifest=validated,
        artifact_links=(link,),
        envelope=ValidatedAcquisitionEnvelope(
            attempt, (publication_row,), (publication_membership,), lineage
        ),
    )
    repository.register_acquisition(fetch)

    run_envelope, report_artifact, run_values, report_values = _run_report_values(label)
    run = cast(
        ResearchRunRow,
        {
            **run_values,
            "run_id": run_id,
            "scope_id": scope.scope_id,
            "catalog_version": catalog.catalog_version,
            "catalog_content_hash": catalog.catalog_content_hash,
            "drug_concept_ids": [item.concept_id for item in scope.drugs],
            "adverse_event_concept_ids": [item.concept_id for item in scope.adverse_reactions],
            "pubmed_query": build_pubmed_query(scope, catalog),
            "created_at_utc": manifest.started_at_utc,
            "started_at_utc": manifest.started_at_utc,
            "completed_at_utc": manifest.completed_at_utc,
            "coverage_status": "complete",
            "result_status": "matches",
        },
    )
    report = cast(
        ResearchReportRow,
        {
            **report_values,
            "run_id": run_id,
            "created_at_utc": manifest.completed_at_utc,
            "coverage_status": "complete",
            "result_status": "matches",
        },
    )
    repository.register_run_and_report(
        RunReportRegistration(
            artifacts=(run_envelope, report_artifact),
            run=run,
            report=report,
            lineage=(
                _lineage(run_envelope, report_artifact, "run_envelope_to_report"),
                _lineage(report_artifact, publication_artifact, "report_to_publication"),
            ),
            acquisition_references=(
                (0, search.attempt["registration_envelope_id"]),
                (1, attempt["registration_envelope_id"]),
            ),
        )
    )
    assert repository.get_run(run_id) is not None
    assert repository.get_snapshot(manifest.manifest_id) is not None


@pytest.mark.parametrize("included", (True, False))  # type: ignore[untyped-decorator]
def test_pg_anchor_and_full_material_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, included: bool
) -> None:
    if not os.environ.get(DATABASE_URL_ENV):
        pytest.skip(f"{DATABASE_URL_ENV} is required")
    connection_prefix, database_name = os.environ[DATABASE_URL_ENV].rsplit("/", 1)
    if (
        not connection_prefix.endswith("@127.0.0.1:55434")
        or database_name != "mdev_v1_pubmed_material"
    ):
        pytest.fail("dedicated PubMed material database is required")
    case_database = f"mdev_v1_pubmed_material_{'included' if included else 'excluded'}"
    admin_url = (connection_prefix + "/postgres").replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=10) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (case_database,)
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER offline").format(sql.Identifier(case_database))
            )
    monkeypatch.setenv(DATABASE_URL_ENV, f"{connection_prefix}/{case_database}")
    command.upgrade(Config("alembic.ini"), "head")
    run_id = (
        "run:12345678-1234-4234-9234-123456789abf"
        if included
        else "run:12345678-1234-4234-9234-123456789ac0"
    )
    _, source_repository, snapshots, publication, binding, scope, catalog = _fixture(
        tmp_path, monkeypatch, included=included, run_id=run_id
    )
    digest = binding.snapshot_id.removeprefix("sha256:")
    manifest_path = f"pubmed/manifests/sha256/{digest[:2]}/{digest}.json"
    manifest = SnapshotManifest.from_json_bytes((snapshots.root / manifest_path).read_bytes())
    repository = PersistenceRepository(PersistenceSettings.from_env())
    try:
        _register_source_metadata(
            repository,
            run_id=run_id,
            source_metadata=source_repository.metadata,
            manifest=manifest,
            manifest_path=manifest_path,
            label=f"pubmed-material-{'included' if included else 'excluded'}-{run_id[-3:]}",
            scope=scope,
            catalog=catalog,
        )
        provenance = VerifiedEvidenceProvenanceStore(snapshots=snapshots, repository=repository)
        store = SnapshotPubMedMaterialStore(
            snapshots=snapshots, repository=repository, provenance=provenance
        )
        arguments = dict(
            run_id=run_id,
            scope=scope,
            catalog=catalog,
            publication=publication,
            binding=binding,
        )
        selection = store.materialize(**arguments)
        assert (selection.evidence is not None) is included
        assert store.materialize(**arguments) == selection
        assert (
            store.load_verified_selection(
                run_id=run_id,
                scope=scope,
                catalog=catalog,
                publication_version_id=publication.publication_version_id,
                snapshot_id=binding.snapshot_id,
            )
            == selection
        )
        anchor = repository.get_evidence_provenance_anchor(
            run_id=run_id, evidence_id=selection.source_reference.evidence_id
        )
        assert anchor is not None
        assert anchor["source"] == "pubmed"
        assert anchor["snapshot_id"] == binding.snapshot_id
    finally:
        repository.close()
