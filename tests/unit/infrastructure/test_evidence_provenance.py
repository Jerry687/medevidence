"""Forward PubMed provenance from real immutable synthetic snapshot bytes."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from tests.unit.tools.test_report_validation import _material_request

from medevidence.connectors.pubmed.client import reconcile_retained_fetch_response
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.domain import (
    CoverageStatus,
    ExecutionStatus,
    PublicationRecord,
    ResultStatus,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.domain.provenance import (
    EvidenceProvenanceEnvelopeV1,
    ProvenanceParentKind,
    ProvenanceParentRefV1,
)
from medevidence.infrastructure.evidence_provenance import (
    EvidenceProvenanceIntegrityError,
    PubMedSourceCaptureProof,
    VerifiedEvidenceProvenanceStore,
)
from medevidence.ingestion.artifacts import ManifestFile, SnapshotManifest
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.persistence.repositories import SnapshotMetadata
from medevidence.tools.ports import (
    PersistedPublicationBinding,
    PersistedPublicationLineageEdge,
)
from medevidence.tools.report_validation import canonical_evidence_id

RUN_ID = "run:12345678-1234-4234-9234-123456789abd"


class SnapshotMetadataRepository:
    """Test metadata boundary; parent files are real SnapshotStore publications."""

    def __init__(self, metadata: SnapshotMetadata) -> None:
        self.metadata = metadata
        self.anchors: dict[tuple[str, str], dict[str, object]] = {}

    def get_snapshot(self, snapshot_id: str) -> SnapshotMetadata | None:
        return self.metadata if snapshot_id == self.metadata.snapshot["snapshot_id"] else None

    def insert_or_verify_evidence_provenance(
        self, envelope: EvidenceProvenanceEnvelopeV1
    ) -> dict[str, object]:
        digest = envelope.envelope_hash.removeprefix("sha256:")
        row: dict[str, object] = {
            "run_id": envelope.run_id,
            "evidence_id": envelope.evidence_id,
            "source": envelope.source.value,
            "snapshot_id": envelope.snapshot_id,
            "envelope_id": envelope.envelope_id,
            "envelope_hash": envelope.envelope_hash,
            "relative_path": f"m3/evidence-provenance/{digest[:2]}/{digest}.json",
            "byte_size": len(envelope.canonical_bytes()),
        }
        key = (envelope.run_id, envelope.evidence_id)
        if key in self.anchors and self.anchors[key] != row:
            raise ValueError("immutable test anchor collision")
        self.anchors[key] = row
        return row

    def get_evidence_provenance_anchor(
        self, *, run_id: str, evidence_id: str
    ) -> dict[str, object] | None:
        return self.anchors.get((run_id, evidence_id))


def _case(
    tmp_path: Path,
    *,
    query_id: str = "query:synthetic",
    run_id: str = RUN_ID,
    acquisition_intent_id: str = "acquisition-intent:sha256:" + "b" * 64,
    artifact_link_id: str = "artifact-link:sha256:" + "a" * 64,
):
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    raw = Path("tests/fixtures/pubmed/valid_fetch.xml").read_bytes()
    raw_hash = sha256_digest(raw)
    raw_digest = raw_hash.removeprefix("sha256:")
    raw_path = f"pubmed/sha256/{raw_digest[:2]}/{raw_digest}.bin"
    manifest_file = ManifestFile(
        ordinal=0,
        link_id=artifact_link_id,
        artifact_id=raw_hash,
        relative_path=raw_path,
        byte_size=len(raw),
        media_type="application/xml",
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    manifest = SnapshotManifest(
        acquisition_intent_id=acquisition_intent_id,
        request_identity=query_id,
        started_at_utc=datetime(2026, 7, 27, 11, 59, 59, tzinfo=UTC),
        completed_at_utc=datetime(2026, 7, 27, 12, 0, 1, tzinfo=UTC),
        record_count=1,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
        files=(manifest_file,),
        code_revision="0" * 40,
    )
    reconciled = reconcile_retained_fetch_response(
        raw,
        ("111",),
        query_id=query_id,
        retrieved_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
        config=PubMedConnectorConfig(),
    )
    assert len(reconciled.publications) == 1
    record = reconciled.publications[0]
    record = PublicationRecord.model_validate(record.model_dump(mode="python"), strict=True)
    normalized = canonical_json(record.version_payload()).encode("utf-8")
    normalized_digest = record.content_hash.removeprefix("sha256:")
    normalized_path = f"pubmed/publications/sha256/{normalized_digest[:2]}/{normalized_digest}.json"
    manifest_digest = manifest.manifest_id.removeprefix("sha256:")
    manifest_path = f"pubmed/manifests/sha256/{manifest_digest[:2]}/{manifest_digest}.json"
    with snapshots.writer():
        snapshots.publish_bytes(raw_path, raw, artifact_class="raw")
        snapshots.publish_bytes(normalized_path, normalized, artifact_class="journal")
        snapshots.publish_bytes(
            manifest_path, manifest.canonical_bytes(), artifact_class="manifest"
        )
    base_evidence = _material_request().registry.evidence[0]
    evidence = replace(
        base_evidence,
        authorized_run_id=run_id,
        source_record_id=record.pmid,
        source_version=record.publication_version_id,
        snapshot_id=manifest.manifest_id,
        content_hash=record.content_hash,
    )
    evidence = replace(evidence, evidence_id=canonical_evidence_id(evidence))
    binding = PersistedPublicationBinding(
        pmid=record.pmid,
        publication_version_id=record.publication_version_id,
        publication_artifact_id=record.content_hash,
        snapshot_id=manifest.manifest_id,
        manifest_id=manifest.manifest_id,
        artifact_ids=tuple(sorted({record.content_hash, manifest.manifest_id})),
        lineage_edges=(
            PersistedPublicationLineageEdge(
                parent_artifact_id=record.content_hash,
                child_artifact_id=manifest.manifest_id,
            ),
        ),
    )
    row = {
        "publication_version_id": record.publication_version_id,
        "source": "pubmed",
        "pmid": record.pmid,
        "content_hash": record.content_hash,
        "publication_status_identity": record.publication_status.publication_status_identity,
        "publication_status": record.publication_status.status.value,
        "status_retrieved_at_utc": record.publication_status.retrieved_as_of,
        "version_payload": json.loads(normalized),
        "publication_artifact_id": record.content_hash,
        "publication_artifact_kind": "publication_record",
        "publication_source_partition": "pubmed",
        "publication_artifact_hash": record.content_hash,
        "schema_version": "1.0",
    }
    metadata = SnapshotMetadata(
        snapshot={
            "snapshot_id": manifest.manifest_id,
            "source": "pubmed",
            "manifest_artifact_id": manifest.manifest_id,
            "manifest_content_hash": manifest.manifest_id,
            "acquisition_intent_id": manifest.acquisition_intent_id,
            "request_identity": manifest.request_identity,
            "completed_at_utc": manifest.completed_at_utc,
            "record_count": 1,
        },  # type: ignore[arg-type]
        files=(
            {
                "raw_artifact_id": raw_hash,
                "raw_content_hash": raw_hash,
                "relative_storage_path": raw_path,
                "byte_size": len(raw),
            },  # type: ignore[typeddict-item]
        ),
        memberships=(),
        warnings=(),
        publications=(row,),  # type: ignore[arg-type]
        publication_memberships=(
            {
                "publication_version_id": record.publication_version_id,
                "pmid": record.pmid,
                "publication_content_hash": record.content_hash,
            },  # type: ignore[typeddict-item]
        ),
        lineage=(
            {
                "lineage_type": "manifest_to_raw_response",
                "parent_artifact_id": manifest.manifest_id,
                "child_artifact_id": raw_hash,
            },  # type: ignore[typeddict-item]
            {
                "lineage_type": "publication_to_manifest",
                "parent_artifact_id": record.content_hash,
                "child_artifact_id": manifest.manifest_id,
            },  # type: ignore[typeddict-item]
        ),
        attempt={"run_id": run_id},  # type: ignore[typeddict-item]
    )
    repository = SnapshotMetadataRepository(metadata)
    reader = VerifiedEvidenceProvenanceStore(
        snapshots=snapshots,
        repository=repository,  # type: ignore[arg-type]
    )
    proof = PubMedSourceCaptureProof(record, binding, evidence)
    return reader, repository, proof, snapshots


def _load(reader: VerifiedEvidenceProvenanceStore, proof: PubMedSourceCaptureProof):
    evidence = proof.evidence
    return reader.load_verified_provenance(
        run_id=evidence.authorized_run_id,
        evidence_id=evidence.evidence_id,
        source=evidence.source,
        source_record_id=evidence.source_record_id,
        source_version=evidence.source_version,
        snapshot_id=evidence.snapshot_id,
        content_hash=evidence.content_hash,
    )


def test_forward_pubmed_capture_reads_only_verified_immutable_source(tmp_path: Path) -> None:
    reader, _, proof, _ = _case(tmp_path)
    assert _load(reader, proof) is None
    envelope = reader.publish_pubmed(proof)
    result = _load(reader, proof)
    assert result is not None
    assert result.lookup_key == f"pmid:{proof.publication.pmid}"
    assert result.source_url is None
    assert result.retrieved_at == proof.publication.publication_status.retrieved_as_of
    assert result.transformation_lineage == envelope.transformation_lineage
    assert reader.publish_pubmed(proof) == envelope
    assert (
        reader.load_verified_provenance(
            run_id=proof.evidence.authorized_run_id,
            evidence_id=proof.evidence.evidence_id,
            source=SourceType.DAILYMED,
            source_record_id=proof.evidence.source_record_id,
            source_version=proof.evidence.source_version,
            snapshot_id=proof.evidence.snapshot_id,
            content_hash=proof.evidence.content_hash,
        )
        is None
    )


@pytest.mark.parametrize("field", ("lookup_key", "retrieved_at", "transformation_lineage"))
def test_tampered_envelope_metadata_with_same_anchor_fails_closed(
    tmp_path: Path, field: str
) -> None:
    reader, repository, proof, snapshots = _case(tmp_path)
    reader.publish_pubmed(proof)
    anchor = repository.anchors[(RUN_ID, proof.evidence.evidence_id)]
    target = snapshots.root.joinpath(*Path(str(anchor["relative_path"])).parts)
    original = target.read_bytes()
    payload = json.loads(original)
    payload[field] = {
        "lookup_key": "pmid:foreign",
        "retrieved_at": "2026-01-02T00:00:00.000000Z",
        "transformation_lineage": ["sha256:" + "0" * 64, proof.evidence.content_hash],
    }[field]
    target.write_bytes(canonical_json(payload).encode("utf-8"))
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)
    target.write_bytes(original)


def test_parent_tamper_foreign_key_and_traversal_fail_closed(tmp_path: Path) -> None:
    reader, repository, proof, snapshots = _case(tmp_path)
    envelope = reader.publish_pubmed(proof)
    with pytest.raises(EvidenceProvenanceIntegrityError):
        reader.load_verified_provenance(
            run_id=RUN_ID,
            evidence_id=proof.evidence.evidence_id,
            source=SourceType.PUBMED,
            source_record_id="12345-foreign",
            source_version=proof.evidence.source_version,
            snapshot_id=proof.evidence.snapshot_id,
            content_hash=proof.evidence.content_hash,
        )
    with pytest.raises(ValueError):
        ProvenanceParentRefV1(
            kind=ProvenanceParentKind.RAW,
            artifact_id=envelope.parent_artifacts[1].artifact_id,
            relative_path="../outside.bin",
            byte_size=3,
        )
    raw_ref = envelope.parent_artifacts[1]
    raw_target = snapshots.root.joinpath(*Path(raw_ref.relative_path).parts)
    raw_target.write_bytes(b"tampered")
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)
    assert repository.anchors


def test_missing_parent_and_anchor_source_mismatch_fail_closed(tmp_path: Path) -> None:
    reader, repository, proof, snapshots = _case(tmp_path)
    envelope = reader.publish_pubmed(proof)
    key = (RUN_ID, proof.evidence.evidence_id)
    original_anchor = repository.anchors[key]
    repository.anchors[key] = {**original_anchor, "source": "faers"}
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)
    repository.anchors[key] = {**original_anchor, "envelope_hash": "sha256:../../outside"}
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)
    repository.anchors[key] = original_anchor
    parent = envelope.parent_artifacts[2]
    target = snapshots.root.joinpath(*Path(parent.relative_path).parts)
    target.unlink()
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)


def test_parent_growth_after_integrity_probe_is_read_with_exact_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, _, proof, snapshots = _case(tmp_path)
    envelope = reader.publish_pubmed(proof)
    parent = envelope.parent_artifacts[1]
    target = snapshots.root.joinpath(*Path(parent.relative_path).parts)
    original_bytes = target.read_bytes()
    original_open = Path.open

    def growing_open(path: Path, *args: object, **kwargs: object):
        if path == target:
            return BytesIO(original_bytes + b"grew-after-probe")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)


def test_symlink_parent_is_rejected_when_host_supports_symlinks(tmp_path: Path) -> None:
    reader, _, proof, snapshots = _case(tmp_path)
    envelope = reader.publish_pubmed(proof)
    parent = envelope.parent_artifacts[1]
    target = snapshots.root.joinpath(*Path(parent.relative_path).parts)
    backup = target.with_name("held-original.bin")
    target.rename(backup)
    try:
        target.symlink_to(backup)
    except OSError:
        pytest.skip("local host cannot create an unprivileged file symlink")
    with pytest.raises(EvidenceProvenanceIntegrityError):
        _load(reader, proof)
