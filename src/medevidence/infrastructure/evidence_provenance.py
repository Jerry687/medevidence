"""Verified forward PubMed provenance capture and immutable source reader."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC
from pathlib import PurePosixPath
from typing import Protocol, final

from medevidence.connectors.pubmed.client import reconcile_retained_fetch_response
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.domain import PublicationRecord, SourceType, canonical_json, sha256_digest
from medevidence.domain.provenance import (
    EvidenceProvenanceEnvelopeV1,
    ProvenanceParentKind,
    ProvenanceParentRefV1,
)
from medevidence.ingestion.artifacts import SnapshotManifest
from medevidence.ingestion.snapshots import (
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.persistence.repositories import (
    PersistenceRepository,
    PublicationVersionRow,
    SnapshotMetadata,
)
from medevidence.tools.ports import PersistedPublicationBinding
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.report_validation import EvidenceInput, canonical_evidence_id


class EvidenceProvenanceIntegrityError(ValueError):
    """An anchored source, parent artifact, or provenance field differs."""


class M1BVerifiedProvenancePort(Protocol):
    def load_verified_provenance(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> EvidenceProvenanceV1 | None: ...


@dataclass(frozen=True, slots=True)
class PubMedSourceCaptureProof:
    """Forward capture from an executed PubMed publication and persisted binding."""

    publication: PublicationRecord
    binding: PersistedPublicationBinding
    evidence: EvidenceInput


def _artifact_path(kind: ProvenanceParentKind, digest: str) -> str:
    value = digest.removeprefix("sha256:")
    if kind is ProvenanceParentKind.MANIFEST:
        return f"pubmed/manifests/sha256/{value[:2]}/{value}.json"
    if kind is ProvenanceParentKind.RAW:
        return f"pubmed/sha256/{value[:2]}/{value}.bin"
    return f"pubmed/publications/sha256/{value[:2]}/{value}.json"


def _envelope_path(envelope_hash: str) -> str:
    digest = envelope_hash.removeprefix("sha256:")
    return f"m3/evidence-provenance/{digest[:2]}/{digest}.json"


@final
class VerifiedEvidenceProvenanceStore:
    """Read anchored bytes and publish only a fully replayed PubMed capture."""

    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        repository: PersistenceRepository,
        m1b: M1BVerifiedProvenancePort | None = None,
        dailymed_v2: M1BVerifiedProvenancePort | None = None,
        cadec: M1BVerifiedProvenancePort | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._repository = repository
        self._m1b = m1b
        self._dailymed_v2 = dailymed_v2
        self._cadec = cadec

    def _read_exact(self, relative: str, artifact_id: str, byte_size: int) -> bytes:
        target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)
        try:
            self._snapshots._verify_file(target, artifact_id.removeprefix("sha256:"), byte_size)
            if byte_size > 5_242_880:
                raise EvidenceProvenanceIntegrityError("source parent exceeds byte bound")
            with target.open("rb") as stream:
                raw = stream.read(byte_size + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            if len(raw) != byte_size or sha256_digest(raw) != artifact_id:
                raise EvidenceProvenanceIntegrityError("source parent changed during read")
            return raw
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError(
                "source parent bytes are unavailable or invalid"
            ) from error

    def _verify_parent(self, ref: ProvenanceParentRefV1) -> bytes:
        if ref.relative_path != _artifact_path(ref.kind, ref.artifact_id):
            raise EvidenceProvenanceIntegrityError("source parent path differs from identity")
        return self._read_exact(ref.relative_path, ref.artifact_id, ref.byte_size)

    def _pubmed_context(
        self, envelope: EvidenceProvenanceEnvelopeV1
    ) -> tuple[SnapshotMetadata, PublicationVersionRow]:
        metadata = self._repository.get_snapshot(envelope.snapshot_id)
        if metadata is None or metadata.attempt is None:
            raise EvidenceProvenanceIntegrityError("source snapshot or attempt is unavailable")
        snapshot = metadata.snapshot
        if (
            metadata.attempt["run_id"] != envelope.run_id
            or snapshot["source"] != SourceType.PUBMED.value
            or snapshot["snapshot_id"] != envelope.snapshot_id
            or snapshot["manifest_artifact_id"] != envelope.snapshot_id
            or snapshot["manifest_content_hash"] != envelope.snapshot_id
        ):
            raise EvidenceProvenanceIntegrityError("source snapshot ownership differs")
        matching = tuple(
            item
            for item in metadata.publications
            if item["publication_version_id"] == envelope.source_version
            and item["pmid"] == envelope.source_record_id
            and item["content_hash"] == envelope.content_hash
        )
        if len(matching) != 1:
            raise EvidenceProvenanceIntegrityError(
                "publication version is not an exact snapshot member"
            )
        publication = matching[0]
        members = tuple(
            item
            for item in metadata.publication_memberships
            if item["publication_version_id"] == envelope.source_version
            and item["pmid"] == envelope.source_record_id
            and item["publication_content_hash"] == envelope.content_hash
        )
        if len(members) != 1:
            raise EvidenceProvenanceIntegrityError("publication membership differs")
        try:
            PersistenceRepository._validate_publication(publication)
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError(
                "stored publication payload is invalid"
            ) from error
        return metadata, publication

    def _verify_pubmed(self, envelope: EvidenceProvenanceEnvelopeV1) -> None:
        if envelope.source is not SourceType.PUBMED:
            raise EvidenceProvenanceIntegrityError("source capture reader is unavailable")
        metadata, publication = self._pubmed_context(envelope)
        manifest_ref, raw_ref, normalized_ref = envelope.parent_artifacts
        retrieved = publication["status_retrieved_at_utc"]
        if retrieved.tzinfo is None or retrieved.utcoffset() is None:
            raise EvidenceProvenanceIntegrityError("publication retrieval time is not UTC aware")
        if (
            manifest_ref.artifact_id != envelope.snapshot_id
            or normalized_ref.artifact_id != envelope.content_hash
            or envelope.source_url is not None
            or envelope.lookup_key != f"pmid:{publication['pmid']}"
            or envelope.retrieved_at != retrieved.astimezone(UTC)
            or envelope.transformation_lineage != (raw_ref.artifact_id, normalized_ref.artifact_id)
        ):
            raise EvidenceProvenanceIntegrityError("publication provenance differs from source")
        manifest_raw = self._verify_parent(manifest_ref)
        raw = self._verify_parent(raw_ref)
        normalized = self._verify_parent(normalized_ref)
        try:
            manifest = SnapshotManifest.from_json_bytes(manifest_raw)
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError("source manifest bytes are invalid") from error
        if (
            manifest.manifest_id != envelope.snapshot_id
            or manifest.source_type != SourceType.PUBMED.value
            or manifest.acquisition_intent_id != metadata.snapshot["acquisition_intent_id"]
            or manifest.completed_at_utc != metadata.snapshot["completed_at_utc"]
            or not manifest.started_at_utc <= retrieved <= manifest.completed_at_utc
            or manifest.record_count != metadata.snapshot["record_count"]
            or normalized != canonical_json(publication["version_payload"]).encode("utf-8")
        ):
            raise EvidenceProvenanceIntegrityError("manifest or normalized publication differs")
        matching_files = tuple(
            item
            for item in metadata.files
            if item["raw_artifact_id"] == raw_ref.artifact_id
            and item["raw_content_hash"] == raw_ref.artifact_id
            and item["relative_storage_path"] == raw_ref.relative_path
            and item["byte_size"] == len(raw)
        )
        matching_manifest_files = tuple(
            item
            for item in manifest.files
            if item.artifact_id == raw_ref.artifact_id
            and item.relative_path == raw_ref.relative_path
            and item.byte_size == len(raw)
        )
        edges = {
            (row["lineage_type"], row["parent_artifact_id"], row["child_artifact_id"])
            for row in metadata.lineage
        }
        if (
            len(matching_files) != 1
            or len(matching_manifest_files) != 1
            or (
                "manifest_to_raw_response",
                envelope.snapshot_id,
                raw_ref.artifact_id,
            )
            not in edges
            or ("publication_to_manifest", envelope.content_hash, envelope.snapshot_id) not in edges
        ):
            raise EvidenceProvenanceIntegrityError("raw publication lineage differs")
        try:
            replayed = reconcile_retained_fetch_response(
                raw,
                (envelope.source_record_id,),
                query_id=metadata.snapshot["request_identity"],
                retrieved_at=retrieved.astimezone(UTC),
                config=PubMedConnectorConfig(),
            )
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError(
                "retained PubMed raw replay is invalid"
            ) from error
        if len(replayed.publications) != 1 or (
            replayed.publications[0].publication_version_id,
            replayed.publications[0].content_hash,
            canonical_json(replayed.publications[0].version_payload()).encode("utf-8"),
        ) != (envelope.source_version, envelope.content_hash, normalized):
            raise EvidenceProvenanceIntegrityError(
                "raw publication does not reproduce normalized version"
            )

    def publish_pubmed(self, proof: PubMedSourceCaptureProof) -> EvidenceProvenanceEnvelopeV1:
        """Record a forward-only publication after exact snapshot and source replay."""

        if type(proof) is not PubMedSourceCaptureProof:
            raise TypeError("PubMed provenance requires a concrete capture proof")
        publication = PublicationRecord.model_validate(
            proof.publication.model_dump(mode="python"), strict=True
        )
        binding = PersistedPublicationBinding.model_validate(
            proof.binding.model_dump(mode="python"), strict=True
        )
        evidence = proof.evidence
        if (
            type(evidence) is not EvidenceInput
            or evidence.evidence_id != canonical_evidence_id(evidence)
            or evidence.source is not SourceType.PUBMED
            or evidence.source_record_id != publication.pmid
            or evidence.source_version != publication.publication_version_id
            or evidence.snapshot_id != binding.snapshot_id
            or evidence.content_hash != publication.content_hash
            or (binding.pmid, binding.publication_version_id, binding.publication_artifact_id)
            != (publication.pmid, publication.publication_version_id, publication.content_hash)
            or publication.provenance.source_record_id != publication.pmid
            or publication.provenance.source_lookup_key != f"pmid:{publication.pmid}"
            or publication.provenance.content_hash == publication.content_hash
        ):
            raise EvidenceProvenanceIntegrityError(
                "publication capture proof differs from evidence"
            )
        raw_id = publication.provenance.content_hash
        parents = tuple(
            ProvenanceParentRefV1(
                kind=kind,
                artifact_id=digest,
                relative_path=_artifact_path(kind, digest),
                byte_size=self._contained_size(_artifact_path(kind, digest)),
            )
            for kind, digest in (
                (ProvenanceParentKind.MANIFEST, evidence.snapshot_id),
                (ProvenanceParentKind.RAW, raw_id),
                (ProvenanceParentKind.NORMALIZED, evidence.content_hash),
            )
        )
        envelope = EvidenceProvenanceEnvelopeV1.create(
            run_id=evidence.authorized_run_id,
            evidence_id=evidence.evidence_id,
            source=SourceType.PUBMED,
            source_record_id=publication.pmid,
            source_version=publication.publication_version_id,
            snapshot_id=evidence.snapshot_id,
            content_hash=evidence.content_hash,
            source_url=None,
            lookup_key=f"pmid:{publication.pmid}",
            retrieved_at=publication.publication_status.retrieved_as_of,
            transformation_lineage=(raw_id, evidence.content_hash),
            parent_artifacts=parents,
        )
        self._verify_pubmed(envelope)
        relative = _envelope_path(envelope.envelope_hash)
        data = envelope.canonical_bytes()
        if self._snapshots.has_writer_lock:
            self._snapshots.publish_bytes(relative, data, artifact_class="journal")
        else:
            with self._snapshots.writer():
                self._snapshots.publish_bytes(relative, data, artifact_class="journal")
        anchor = self._repository.insert_or_verify_evidence_provenance(envelope)
        if (
            anchor["run_id"] != envelope.run_id
            or anchor["evidence_id"] != envelope.evidence_id
            or anchor["source"] != envelope.source.value
            or anchor["snapshot_id"] != envelope.snapshot_id
            or anchor["envelope_id"] != envelope.envelope_id
            or anchor["envelope_hash"] != envelope.envelope_hash
            or anchor["relative_path"] != relative
            or anchor["byte_size"] != len(data)
        ):
            raise EvidenceProvenanceIntegrityError("persisted provenance anchor differs")
        return envelope

    def _contained_size(self, relative: str) -> int:
        target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError("source parent size is unavailable") from error
        if not 1 <= size <= 5_242_880:
            raise EvidenceProvenanceIntegrityError("source parent byte size is invalid")
        return size

    def load_verified_provenance(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> EvidenceProvenanceV1 | None:
        """Dispatch to source-specific replay and preserve exact PubMed behavior."""

        if source is not SourceType.PUBMED:
            if source is SourceType.CADEC:
                if self._cadec is None:
                    return None
                return self._cadec.load_verified_provenance(
                    run_id=run_id,
                    evidence_id=evidence_id,
                    source=source,
                    source_record_id=source_record_id,
                    source_version=source_version,
                    snapshot_id=snapshot_id,
                    content_hash=content_hash,
                )
            if source is SourceType.DAILYMED and source_record_id.startswith(
                "dailymed-v2-section-chunk:sha256:"
            ):
                if self._dailymed_v2 is None:
                    return None
                return self._dailymed_v2.load_verified_provenance(
                    run_id=run_id,
                    evidence_id=evidence_id,
                    source=source,
                    source_record_id=source_record_id,
                    source_version=source_version,
                    snapshot_id=snapshot_id,
                    content_hash=content_hash,
                )
            if self._m1b is None:
                return None
            return self._m1b.load_verified_provenance(
                run_id=run_id,
                evidence_id=evidence_id,
                source=source,
                source_record_id=source_record_id,
                source_version=source_version,
                snapshot_id=snapshot_id,
                content_hash=content_hash,
            )
        anchor = self._repository.get_evidence_provenance_anchor(
            run_id=run_id, evidence_id=evidence_id
        )
        if anchor is None:
            return None
        if (
            anchor["run_id"] != run_id
            or anchor["evidence_id"] != evidence_id
            or anchor["source"] != source.value
            or anchor["snapshot_id"] != snapshot_id
        ):
            raise EvidenceProvenanceIntegrityError("provenance anchor identity differs")
        envelope_hash = anchor["envelope_hash"]
        if (
            type(envelope_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", envelope_hash) is None
        ):
            raise EvidenceProvenanceIntegrityError("provenance anchor hash is invalid")
        relative = _envelope_path(envelope_hash)
        if anchor["relative_path"] != relative:
            raise EvidenceProvenanceIntegrityError("provenance anchor path differs")
        byte_size = anchor["byte_size"]
        if type(byte_size) is not int or not 1 <= byte_size <= 32_768:
            raise EvidenceProvenanceIntegrityError("provenance anchor byte size is invalid")
        raw = self._read_exact(relative, envelope_hash, byte_size)
        try:
            envelope = EvidenceProvenanceEnvelopeV1.from_canonical_bytes(raw)
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError(
                "provenance envelope bytes are invalid"
            ) from error
        if (
            envelope.envelope_id != anchor["envelope_id"]
            or envelope.envelope_hash != envelope_hash
            or (
                envelope.run_id,
                envelope.evidence_id,
                envelope.source,
                envelope.source_record_id,
                envelope.source_version,
                envelope.snapshot_id,
                envelope.content_hash,
            )
            != (
                run_id,
                evidence_id,
                source,
                source_record_id,
                source_version,
                snapshot_id,
                content_hash,
            )
        ):
            raise EvidenceProvenanceIntegrityError("provenance envelope request binding differs")
        self._verify_pubmed(envelope)
        return EvidenceProvenanceV1(
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
            source_url=envelope.source_url,
            lookup_key=envelope.lookup_key,
            retrieved_at=envelope.retrieved_at,
            transformation_lineage=tuple(envelope.transformation_lineage),
        )
