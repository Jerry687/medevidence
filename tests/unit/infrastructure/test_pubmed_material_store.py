"""Offline source replay, exclusion retention, and material integrity failures."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from tests.unit.infrastructure.test_evidence_provenance import RUN_ID, _case
from tests.unit.tools.test_pubmed_local_bounds import LocalCatalog
from tests.unit.tools.test_research import _scope

from medevidence.domain import PublicationRecord, canonical_json, sha256_digest
from medevidence.infrastructure.pubmed_material_store import (
    PubMedMaterialStoreError,
    SnapshotPubMedMaterialStore,
    _selection_hash,
)
from medevidence.ingestion.artifacts import SnapshotManifest
from medevidence.persistence.repositories import PersistenceRepository, RunMetadata
from medevidence.tools.pubmed import build_pubmed_query, query_identity
from medevidence.tools.pubmed_material import PubMedMaterialExclusion
from medevidence.tools.report_validation import canonical_evidence_id


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, included: bool, run_id: str = RUN_ID
):
    scope = _scope()
    catalog = LocalCatalog(scope).resolve(scope.scope_id)
    query = build_pubmed_query(scope, catalog)
    original = Path.read_bytes

    def source_bytes(path: Path) -> bytes:
        raw = original(path)
        if included and path.as_posix() == "tests/fixtures/pubmed/valid_fetch.xml":
            assert b"First  exact section." in raw
            changed = raw.replace(b"First  exact section.", b"Semaglutide gastrointestinal.", 1)
            notice_start = changed.index(b"      <CommentsCorrectionsList>")
            notice_end = changed.index(b"      </CommentsCorrectionsList>") + len(
                b"      </CommentsCorrectionsList>"
            )
            return changed[:notice_start] + changed[notice_end:]
        return raw

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "read_bytes", source_bytes)
        provenance, repository, proof, snapshots = _case(
            tmp_path,
            query_id=query_identity(scope, query),
            run_id=run_id,
            acquisition_intent_id=f"acquisition-intent:{sha256_digest(run_id.encode())}",
            artifact_link_id=f"artifact-link:{sha256_digest(run_id.encode())}",
        )
    digest = proof.binding.snapshot_id.removeprefix("sha256:")
    manifest_path = (
        snapshots.root / "pubmed" / "manifests" / "sha256" / digest[:2] / f"{digest}.json"
    )
    manifest = SnapshotManifest.from_json_bytes(manifest_path.read_bytes())
    repository.metadata = replace(
        repository.metadata,
        snapshot={
            **repository.metadata.snapshot,
            "execution_status": manifest.execution_status.value,
            "coverage_status": manifest.coverage_status.value,
            "result_status": manifest.result_status.value,
            "started_at_utc": manifest.started_at_utc,
            "completed_at_utc": manifest.completed_at_utc,
            "pages_completed": manifest.pages_completed,
            "truncated": manifest.truncated,
        },
    )
    bound_provenance = proof.publication.provenance.model_copy(
        update={
            "snapshot_id": proof.binding.snapshot_id,
            "artifact_ids": proof.binding.artifact_ids,
            "transformation_lineage": (
                proof.publication.content_hash,
                proof.binding.snapshot_id,
            ),
        }
    )
    publication = PublicationRecord.model_validate(
        {**proof.publication.model_dump(mode="python"), "provenance": bound_provenance},
        strict=True,
    )
    attempt = {
        **repository.metadata.attempt,
        "manifest_id": proof.binding.snapshot_id,
        "attempt_id": "attempt:synthetic",
        "acquisition_intent_id": manifest.acquisition_intent_id,
    }
    repository.metadata = replace(repository.metadata, attempt=attempt)
    run_metadata = RunMetadata(
        run={
            "run_id": run_id,
            "source": "pubmed",
            "scope_id": scope.scope_id,
            "catalog_version": catalog.catalog_version,
            "catalog_content_hash": catalog.catalog_content_hash,
            "drug_concept_ids": [item.concept_id for item in scope.drugs],
            "adverse_event_concept_ids": [item.concept_id for item in scope.adverse_reactions],
            "start_date": None,
            "end_date": None,
            "pubmed_query": query,
        },  # type: ignore[arg-type]
        attempts=(attempt,),  # type: ignore[arg-type]
        report=None,
    )
    repository.run_metadata = run_metadata  # type: ignore[attr-defined]
    repository.get_run = lambda run_id: (  # type: ignore[attr-defined]
        repository.run_metadata  # type: ignore[attr-defined]
        if run_id == repository.run_metadata.run["run_id"]  # type: ignore[attr-defined]
        else None
    )
    store = SnapshotPubMedMaterialStore(
        snapshots=snapshots,
        repository=cast(PersistenceRepository, cast(object, repository)),
        provenance=provenance,
    )
    return store, repository, snapshots, publication, proof.binding, scope, catalog


def _read(store, publication, binding, scope, catalog):  # type: ignore[no-untyped-def]
    return store.load_verified_selection(
        run_id="run:12345678-1234-4234-9234-123456789abd",
        scope=scope,
        catalog=catalog,
        publication_version_id=publication.publication_version_id,
        snapshot_id=binding.snapshot_id,
    )


@pytest.mark.parametrize("included", (True, False))
def test_materialize_replays_exact_source_and_retains_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, included: bool
) -> None:
    store, repository, _, publication, binding, scope, catalog = _fixture(
        tmp_path, monkeypatch, included=included
    )
    result = store.materialize(
        run_id="run:12345678-1234-4234-9234-123456789abd",
        scope=scope,
        catalog=catalog,
        publication=publication,
        binding=binding,
    )
    assert _read(store, publication, binding, scope, catalog) == result
    assert result.evidence is not None if included else result.evidence is None
    assert len(repository.anchors) == 1
    if included:
        assert result.exclusion is None and result.citation is not None
        assert result.evidence is not None
        assert result.source_reference == result.evidence
        assert result.evidence.normalized_excerpt == "Semaglutide gastrointestinal"
    else:
        assert result.exclusion is PubMedMaterialExclusion.STATUS_NOT_ELIGIBLE
        assert result.citation is None
        assert not result.source_reference.permitted_claim_classes
        assert not result.source_reference.permitted_inference_uses
        assert result.source_reference.normalized_excerpt == publication.title
    assert (
        store.materialize(
            run_id="run:12345678-1234-4234-9234-123456789abd",
            scope=scope,
            catalog=catalog,
            publication=publication,
            binding=binding,
        )
        == result
    )


@pytest.mark.parametrize(
    "surface",
    (
        "raw",
        "missing_raw",
        "normalized",
        "manifest",
        "membership",
        "run",
        "scope",
        "catalog",
        "query",
        "attempt_membership",
        "attempt_manifest",
        "attempt_intent",
    ),
)
def test_material_reader_rejects_source_and_database_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    store, repository, snapshots, publication, binding, scope, catalog = _fixture(
        tmp_path, monkeypatch, included=True
    )
    result = store.materialize(
        run_id="run:12345678-1234-4234-9234-123456789abd",
        scope=scope,
        catalog=catalog,
        publication=publication,
        binding=binding,
    )
    assert result.evidence is not None
    row = repository.metadata.publications[0]
    if surface in {"raw", "missing_raw"}:
        digest = repository.metadata.files[0]["raw_artifact_id"].removeprefix("sha256:")
        path = snapshots.root / "pubmed" / "sha256" / digest[:2] / f"{digest}.bin"
        if surface == "missing_raw":
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b" ")
    elif surface == "normalized":
        digest = row["content_hash"].removeprefix("sha256:")
        path = snapshots.root / "pubmed" / "publications" / "sha256" / digest[:2] / f"{digest}.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif surface == "manifest":
        digest = binding.snapshot_id.removeprefix("sha256:")
        path = snapshots.root / "pubmed" / "manifests" / "sha256" / digest[:2] / f"{digest}.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif surface == "membership":
        repository.metadata = replace(repository.metadata, publication_memberships=())
    elif surface == "run":
        repository.metadata = replace(
            repository.metadata,
            attempt={
                **repository.metadata.attempt,
                "run_id": "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            },
        )
    elif surface == "attempt_membership":
        repository.run_metadata = replace(  # type: ignore[attr-defined]
            repository.run_metadata,
            attempts=(),  # type: ignore[attr-defined]
        )
    elif surface in {"attempt_manifest", "attempt_intent"}:
        field = "manifest_id" if surface == "attempt_manifest" else "acquisition_intent_id"
        repository.metadata = replace(
            repository.metadata,
            attempt={**repository.metadata.attempt, field: "foreign"},
        )
    else:
        row = dict(repository.run_metadata.run)  # type: ignore[attr-defined]
        row[
            {
                "scope": "scope_id",
                "catalog": "catalog_content_hash",
                "query": "pubmed_query",
            }[surface]
        ] = "foreign"
        repository.run_metadata = replace(repository.run_metadata, run=row)  # type: ignore[attr-defined]
    with pytest.raises(PubMedMaterialStoreError):
        _read(store, publication, binding, scope, catalog)


@pytest.mark.parametrize("included", (True, False))
def test_material_journal_or_source_anchor_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, included: bool
) -> None:
    store, repository, snapshots, publication, binding, scope, catalog = _fixture(
        tmp_path, monkeypatch, included=included
    )
    result = store.materialize(
        run_id="run:12345678-1234-4234-9234-123456789abd",
        scope=scope,
        catalog=catalog,
        publication=publication,
        binding=binding,
    )
    assert result.source_reference.evidence_id in {
        evidence_id for _, evidence_id in repository.anchors
    }
    paths = tuple((snapshots.root / "m3" / "pubmed-material").glob("*/*.json"))
    assert len(paths) == 1
    path = paths[0]
    original = path.read_bytes()
    row = json.loads(original)
    row["selection_hash"] = "sha256:" + "0" * 64
    path.write_bytes(canonical_json(row).encode("utf-8"))
    with pytest.raises(PubMedMaterialStoreError):
        _read(store, publication, binding, scope, catalog)
    path.write_bytes(original)
    repository.anchors.clear()
    with pytest.raises(PubMedMaterialStoreError, match="anchor"):
        _read(store, publication, binding, scope, catalog)


@pytest.mark.parametrize("surface", ("permissions", "quote", "status"))
def test_self_consistent_journal_or_status_forgery_cannot_replace_source_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    store, repository, snapshots, publication, binding, scope, catalog = _fixture(
        tmp_path, monkeypatch, included=True
    )
    result = store.materialize(
        run_id="run:12345678-1234-4234-9234-123456789abd",
        scope=scope,
        catalog=catalog,
        publication=publication,
        binding=binding,
    )
    assert result.evidence is not None and result.citation is not None
    if surface == "status":
        row = dict(repository.metadata.publications[0])
        row["publication_status"] = "retracted"
        repository.metadata = replace(repository.metadata, publications=(row,))
    else:
        path = next((snapshots.root / "m3" / "pubmed-material").glob("*/*.json"))
        journal = json.loads(path.read_bytes())
        if surface == "permissions":
            forged_ref = replace(result.source_reference, permitted_claim_classes=frozenset())
            forged_ref = replace(forged_ref, evidence_id=canonical_evidence_id(forged_ref))
            forged = replace(result, evidence=forged_ref, source_reference=forged_ref)
        else:
            forged = replace(
                result,
                citation=result.citation.model_copy(update={"exact_quote": "forged quote"}),
            )
        journal["selection_hash"] = _selection_hash(forged)
        path.write_bytes(canonical_json(journal).encode("utf-8"))
    with pytest.raises(PubMedMaterialStoreError):
        _read(store, publication, binding, scope, catalog)


def test_missing_or_foreign_journal_never_claims_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, snapshots, publication, binding, scope, catalog = _fixture(
        tmp_path, monkeypatch, included=False
    )
    assert _read(store, publication, binding, scope, catalog) is None
    store.materialize(
        run_id="run:12345678-1234-4234-9234-123456789abd",
        scope=scope,
        catalog=catalog,
        publication=publication,
        binding=binding,
    )
    assert (
        store.load_verified_selection(
            run_id="run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            scope=scope,
            catalog=catalog,
            publication_version_id=publication.publication_version_id,
            snapshot_id=binding.snapshot_id,
        )
        is None
    )
    path = next((snapshots.root / "m3" / "pubmed-material").glob("*/*.json"))
    path.unlink()
    assert _read(store, publication, binding, scope, catalog) is None
