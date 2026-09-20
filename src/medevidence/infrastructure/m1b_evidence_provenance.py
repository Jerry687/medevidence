"""Verified forward DailyMed and FAERS evidence provenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, cast, final

from medevidence.connectors.dailymed.parsing import parse_spl_document
from medevidence.connectors.faers.parsing import parse_count_page
from medevidence.domain import SourceType, canonical_json, derive_identity, sha256_digest
from medevidence.domain.provenance import (
    EvidenceProvenanceEnvelopeV1,
    ProvenanceParentKind,
    ProvenanceParentRefV1,
)
from medevidence.ingestion.artifacts import (
    DailyMedSnapshotManifest,
    FaersSnapshotManifest,
    replay_dailymed_snapshot,
    replay_faers_snapshot,
)
from medevidence.ingestion.snapshots import (
    SOURCE_REPLAY_RECORD_BYTE_CAPACITY,
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.persistence.repositories import (
    DailyMedEvidenceBinding,
    FaersEvidenceBinding,
    M1BSourceParentBinding,
    PersistenceRepository,
)
from medevidence.tools.dailymed import DailyMedFetchExecutionProjection
from medevidence.tools.faers import FaersAggregateExecutionProjection
from medevidence.tools.report_document import EvidenceProvenanceV1

from .evidence_provenance import EvidenceProvenanceIntegrityError


def _envelope_path(envelope_hash: str) -> str:
    digest = envelope_hash.removeprefix("sha256:")
    return f"m3/evidence-provenance/{digest[:2]}/{digest}.json"


def _normalized_path(source: SourceType, content_hash: str) -> str:
    digest = content_hash.removeprefix("sha256:")
    kind = "sections" if source is SourceType.DAILYMED else "buckets"
    return f"{source.value}/normalized/{kind}/sha256/{digest[:2]}/{digest}.txt"


def _capture_path(content_hash: str) -> str:
    digest = content_hash.removeprefix("sha256:")
    return f"m3/evidence-provenance-captures/{digest[:2]}/{digest}.json"


@dataclass(frozen=True, slots=True)
class VerifiedM1BEvidenceMaterial:
    """Verified source text and numerical facts for a later canonical registry builder."""

    provenance: EvidenceProvenanceV1
    locator_ref: str
    normalized_text: str
    numerical_facts: tuple[tuple[str, str], ...]


@final
class VerifiedM1BEvidenceProvenanceStore:
    """Replay original source bytes and PG bindings before publishing an envelope."""

    __slots__ = ("_repository", "_snapshots")
    _repository: PersistenceRepository
    _snapshots: SnapshotStore

    def __init__(self, *, snapshots: SnapshotStore, repository: PersistenceRepository) -> None:
        if type(snapshots) is not SnapshotStore or type(repository) is not PersistenceRepository:
            raise TypeError("M1B provenance requires exact snapshot and repository authorities")
        object.__setattr__(self, "_snapshots", snapshots)
        object.__setattr__(self, "_repository", repository)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("M1B provenance store is immutable")

    def _read_parent(self, parent: M1BSourceParentBinding) -> bytes:
        target = self._snapshots.root.joinpath(*PurePosixPath(parent.relative_path).parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            self._snapshots._verify_file(
                target, parent.content_hash.removeprefix("sha256:"), parent.byte_size
            )
            with target.open("rb") as stream:
                raw = stream.read(parent.byte_size + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError("M1B source parent is unavailable") from error
        if (
            len(raw) != parent.byte_size
            or sha256_digest(raw) != parent.content_hash
            or parent.artifact_id != parent.content_hash
        ):
            raise EvidenceProvenanceIntegrityError("M1B source parent identity drift")
        return raw

    def _publish_bytes(
        self,
        relative: str,
        raw: bytes,
        artifact_class: Literal["raw", "journal", "manifest"],
    ) -> None:
        if self._snapshots.has_writer_lock:
            self._snapshots.publish_bytes(relative, raw, artifact_class=artifact_class)
        else:
            with self._snapshots.writer():
                self._snapshots.publish_bytes(relative, raw, artifact_class=artifact_class)
        target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)
        self._snapshots._require_safe_path(target, allow_missing_leaf=False)
        self._snapshots._verify_file(target, sha256_digest(raw).removeprefix("sha256:"), len(raw))

    @staticmethod
    def _matches_manifest_member(binding: M1BSourceParentBinding, member: object) -> bool:
        return (
            binding.artifact_id,
            binding.content_hash,
            binding.relative_path,
            binding.byte_size,
            binding.artifact_kind,
        ) == (
            getattr(member, "artifact_id", None),
            getattr(member, "content_hash", None),
            getattr(member, "relative_path", None),
            getattr(member, "byte_size", None),
            getattr(member, "artifact_kind", None),
        )

    def _verify_dailymed_source(self, binding: DailyMedEvidenceBinding) -> None:
        manifest_raw = self._read_parent(binding.manifest)
        raw = self._read_parent(binding.raw)
        stable = self._read_parent(binding.stable_spl)
        try:
            manifest = DailyMedSnapshotManifest.from_json_bytes(manifest_raw)
            replay_dailymed_snapshot(
                manifest_raw,
                self._snapshots,
                expected_manifest_id=binding.manifest.content_hash,
                expected_members=manifest.members,
            )
            raw_document = parse_spl_document(
                raw,
                expected_setid=binding.setid,
                expected_spl_version=str(binding.spl_version),
            )
            stable_document = parse_spl_document(
                stable,
                expected_setid=binding.setid,
                expected_spl_version=str(binding.spl_version),
            )
        except (ValueError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError(
                "DailyMed source capture replay failed"
            ) from error
        if (
            manifest.run_id != binding.run_id
            or manifest.acquisition_id != binding.acquisition_id
            or manifest.acquisition_intent_id != binding.acquisition_intent_id
            or manifest.query_id != binding.query_id
            or manifest.snapshot_id != binding.snapshot_id
            or manifest.connector_version != binding.connector_version
            or manifest.completed_at_utc != binding.retrieved_at_utc
            or manifest.selected_setid != binding.setid
            or manifest.selected_spl_version != str(binding.spl_version)
            or raw_document.canonical_text != stable_document.canonical_text
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed source capture binding drift")
        raw_members = tuple(
            item
            for item in manifest.members
            if item.artifact_kind == "dailymed_http_response"
            and item.body_complete
            and item.termination_reason == "complete_response"
        )
        stable_members = tuple(
            item for item in manifest.members if item.artifact_kind == "dailymed_spl_xml"
        )
        if (
            len(raw_members) != 1
            or len(stable_members) != 1
            or not self._matches_manifest_member(binding.raw, raw_members[0])
            or not self._matches_manifest_member(binding.stable_spl, stable_members[0])
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed source parent is not in manifest")

    def _verify_faers_source(self, binding: FaersEvidenceBinding) -> None:
        manifest_raw = self._read_parent(binding.manifest)
        try:
            manifest = FaersSnapshotManifest.from_json_bytes(manifest_raw)
            replay_faers_snapshot(
                manifest_raw,
                self._snapshots,
                expected_manifest_id=binding.manifest.content_hash,
                expected_query=manifest.query,
                expected_members=manifest.members,
            )
        except (ValueError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError("FAERS source capture replay failed") from error
        if (
            manifest.run_id != binding.run_id
            or manifest.acquisition_id != binding.acquisition_id
            or manifest.acquisition_intent_id != binding.acquisition_intent_id
            or manifest.query.query_id != binding.query_id
            or manifest.snapshot_id != binding.snapshot_id
            or manifest.connector_version != binding.connector_version
            or manifest.retrieved_at_utc != binding.retrieved_at_utc
            or not any(
                bucket.bucket_ordinal == binding.bucket_ordinal
                and bucket.reaction_pt == binding.reaction_pt
                and bucket.report_count == binding.report_count
                for bucket in manifest.buckets
            )
        ):
            raise EvidenceProvenanceIntegrityError("FAERS source capture binding drift")
        raw_members = tuple(
            item
            for item in manifest.members
            if item.body_complete and item.termination_reason == "complete_response"
        )
        if len(raw_members) != 1 or not self._matches_manifest_member(binding.raw, raw_members[0]):
            raise EvidenceProvenanceIntegrityError("FAERS source parent is not in manifest")

    def _source_replay_parent(
        self,
        kind: Literal["dailymed-fetch", "faers-aggregate"],
        *,
        run_id: str,
        task_id: str,
        attempt_id: str,
        query_id: str,
        acquisition_intent_id: str,
    ) -> tuple[M1BSourceParentBinding, bytes]:
        relative, _, _ = self._snapshots._source_replay_relative_path(
            kind,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            query_id=query_id,
            acquisition_intent_id=acquisition_intent_id,
        )
        target = self._snapshots.root.joinpath(*relative.parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= SOURCE_REPLAY_RECORD_BYTE_CAPACITY:
                raise ValueError("source replay size is invalid")
            with target.open("rb") as stream:
                raw = stream.read(size + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError("M1B source replay is unavailable") from error
        if len(raw) != size:
            raise EvidenceProvenanceIntegrityError("M1B source replay changed during read")
        digest = sha256_digest(raw)
        return (
            M1BSourceParentBinding(digest, digest, size, relative.as_posix(), "source_replay"),
            raw,
        )

    @staticmethod
    def _parent_payload(value: M1BSourceParentBinding) -> dict[str, object]:
        return {
            "artifact_id": value.artifact_id,
            "content_hash": value.content_hash,
            "byte_size": value.byte_size,
            "relative_path": value.relative_path,
            "artifact_kind": value.artifact_kind,
        }

    @staticmethod
    def _parent_from_payload(value: object) -> M1BSourceParentBinding:
        keys = {"artifact_id", "content_hash", "byte_size", "relative_path", "artifact_kind"}
        if type(value) is not dict or set(value) != keys:
            raise EvidenceProvenanceIntegrityError("M1B capture parent shape is invalid")
        try:
            parent = M1BSourceParentBinding(**value)
        except TypeError as error:
            raise EvidenceProvenanceIntegrityError("M1B capture parent is invalid") from error
        if (
            parent.artifact_id != parent.content_hash
            or not parent.content_hash.startswith("sha256:")
            or not 1 <= parent.byte_size <= 5_242_880
        ):
            raise EvidenceProvenanceIntegrityError("M1B capture parent identity is invalid")
        return parent

    def _capture_parent(
        self,
        *,
        source: SourceType,
        original_manifest: M1BSourceParentBinding,
        raw: M1BSourceParentBinding,
        stable: M1BSourceParentBinding | None,
        replay: M1BSourceParentBinding,
        normalized: M1BSourceParentBinding,
        retrieved_at: object,
    ) -> M1BSourceParentBinding:
        payload = {
            "schema_version": "m3.m1b-evidence-capture.v1",
            "source": source.value,
            "retrieved_at_utc": retrieved_at,
            "original_manifest": self._parent_payload(original_manifest),
            "raw": self._parent_payload(raw),
            "stable": None if stable is None else self._parent_payload(stable),
            "source_replay": self._parent_payload(replay),
            "normalized": self._parent_payload(normalized),
        }
        data = canonical_json(payload).encode("utf-8")
        content_hash = sha256_digest(data)
        relative = _capture_path(content_hash)
        self._publish_bytes(relative, data, "journal")
        return M1BSourceParentBinding(
            content_hash, content_hash, len(data), relative, "m1b_evidence_capture_manifest"
        )

    def _read_capture(self, parent: ProvenanceParentRefV1) -> tuple[dict[str, object], bytes]:
        raw = self._read_envelope_parent(parent)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise EvidenceProvenanceIntegrityError(
                "M1B capture manifest is invalid JSON"
            ) from error
        if type(payload) is not dict or canonical_json(payload).encode("utf-8") != raw:
            raise EvidenceProvenanceIntegrityError("M1B capture manifest is noncanonical")
        if (
            set(payload)
            != {
                "schema_version",
                "source",
                "retrieved_at_utc",
                "original_manifest",
                "raw",
                "stable",
                "source_replay",
                "normalized",
            }
            or payload["schema_version"] != "m3.m1b-evidence-capture.v1"
        ):
            raise EvidenceProvenanceIntegrityError("M1B capture manifest shape is invalid")
        return payload, raw

    def _publish_envelope(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        lookup_key: str,
        retrieved_at: object,
        manifest: M1BSourceParentBinding,
        raw: M1BSourceParentBinding,
        stable: M1BSourceParentBinding | None,
        replay: M1BSourceParentBinding,
        normalized: bytes,
    ) -> EvidenceProvenanceEnvelopeV1:
        content_hash = sha256_digest(normalized)
        normalized_path = _normalized_path(source, content_hash)
        self._publish_bytes(normalized_path, normalized, "journal")
        normalized_parent = M1BSourceParentBinding(
            content_hash, content_hash, len(normalized), normalized_path, "normalized_evidence"
        )
        capture = self._capture_parent(
            source=source,
            original_manifest=manifest,
            raw=raw,
            stable=stable,
            replay=replay,
            normalized=normalized_parent,
            retrieved_at=retrieved_at,
        )
        parents = (
            ProvenanceParentRefV1(
                kind=ProvenanceParentKind.MANIFEST,
                artifact_id=capture.artifact_id,
                relative_path=capture.relative_path,
                byte_size=capture.byte_size,
            ),
            ProvenanceParentRefV1(
                kind=ProvenanceParentKind.RAW,
                artifact_id=raw.artifact_id,
                relative_path=raw.relative_path,
                byte_size=raw.byte_size,
            ),
            ProvenanceParentRefV1(
                kind=ProvenanceParentKind.NORMALIZED,
                artifact_id=content_hash,
                relative_path=normalized_path,
                byte_size=len(normalized),
            ),
        )
        envelope = EvidenceProvenanceEnvelopeV1.create(
            run_id=run_id,
            evidence_id=evidence_id,
            source=source,
            source_record_id=source_record_id,
            source_version=source_version,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
            source_url=None,
            lookup_key=lookup_key,
            retrieved_at=retrieved_at,
            transformation_lineage=tuple(
                dict.fromkeys(
                    (
                        raw.artifact_id,
                        *(() if stable is None else (stable.artifact_id,)),
                        replay.artifact_id,
                        content_hash,
                    )
                )
            ),
            parent_artifacts=parents,
        )
        relative = _envelope_path(envelope.envelope_hash)
        data = envelope.canonical_bytes()
        self._publish_bytes(relative, data, "journal")
        anchor = self._repository.insert_or_verify_evidence_provenance(envelope)
        expected = {
            "run_id": envelope.run_id,
            "evidence_id": envelope.evidence_id,
            "source": envelope.source.value,
            "snapshot_id": envelope.snapshot_id,
            "envelope_id": envelope.envelope_id,
            "envelope_hash": envelope.envelope_hash,
            "relative_path": relative,
            "byte_size": len(data),
        }
        if any(anchor.get(name) != value for name, value in expected.items()):
            raise EvidenceProvenanceIntegrityError("M1B provenance anchor drift")
        return envelope

    def publish_dailymed(
        self, projection: DailyMedFetchExecutionProjection
    ) -> tuple[EvidenceProvenanceEnvelopeV1, ...]:
        """Publish each exact retained section after SPL and source replay."""

        if type(projection) is not DailyMedFetchExecutionProjection:
            raise TypeError("DailyMed provenance requires exact fetch projection")
        exact = DailyMedFetchExecutionProjection.model_validate(
            projection.model_dump(mode="python"), strict=True
        )
        response = exact.response
        if response.label_version_id is None:
            raise EvidenceProvenanceIntegrityError("DailyMed fetch lacks label version")
        replay_parent, replay = self._source_replay_parent(
            "dailymed-fetch",
            run_id=exact.run_id,
            task_id=exact.task_id,
            attempt_id=exact.attempt_id,
            query_id=response.request.query_id,
            acquisition_intent_id=exact.acquisition.acquisition_intent_id,
        )
        if canonical_json(exact).encode("utf-8") != replay:
            raise EvidenceProvenanceIntegrityError("DailyMed source replay differs")
        envelopes: list[EvidenceProvenanceEnvelopeV1] = []
        for item in exact.section_evidence:
            binding = self._repository.get_dailymed_evidence_binding(
                run_id=exact.run_id,
                acquisition_id=exact.acquisition.acquisition_id,
                query_id=response.request.query_id,
                source_outcome_id=response.source_outcome_id,
                snapshot_id=response.fetch_snapshot_id,
                label_version_id=response.label_version_id,
                section_id=item.section_id,
            )
            if binding is None:
                raise EvidenceProvenanceIntegrityError("DailyMed evidence binding is missing")
            self._verify_dailymed_source(binding)
            self._read_parent(binding.manifest)
            self._read_parent(binding.raw)
            spl = self._read_parent(binding.stable_spl)
            try:
                document = parse_spl_document(
                    spl,
                    expected_setid=binding.setid,
                    expected_spl_version=str(binding.spl_version),
                )
            except ValueError as error:
                raise EvidenceProvenanceIntegrityError("DailyMed SPL replay failed") from error
            section_matches = tuple(
                section
                for section in document.sections
                if section.section_code == binding.section_code
                and section.xml_path == binding.xml_path
                and section.text_start == binding.text_start
                and section.text_end == binding.text_end
            )
            if len(section_matches) != 1:
                raise EvidenceProvenanceIntegrityError("DailyMed section replay is ambiguous")
            normalized = section_matches[0].text.encode("utf-8")
            if (
                sha256_digest(normalized) != binding.text_hash
                or item.content_hash != binding.text_hash
            ):
                raise EvidenceProvenanceIntegrityError("DailyMed section content hash drift")
            lookup = canonical_json(
                {
                    "source": "dailymed",
                    "acquisition_id": binding.acquisition_id,
                    "query_id": binding.query_id,
                    "source_outcome_id": binding.source_outcome_id,
                    "label_version_id": binding.label_version_id,
                    "section_id": binding.section_id,
                    "locator_ref": item.locator_ref,
                }
            )
            envelopes.append(
                self._publish_envelope(
                    run_id=binding.run_id,
                    evidence_id=item.evidence_id,
                    source=SourceType.DAILYMED,
                    source_record_id=binding.section_id,
                    source_version=binding.label_version_id,
                    snapshot_id=binding.snapshot_id,
                    lookup_key=lookup,
                    retrieved_at=binding.retrieved_at_utc,
                    manifest=binding.manifest,
                    raw=binding.raw,
                    stable=binding.stable_spl,
                    replay=replay_parent,
                    normalized=normalized,
                )
            )
        return tuple(envelopes)

    @staticmethod
    def _faers_bucket_bytes(binding: FaersEvidenceBinding) -> bytes:
        return canonical_json(
            {
                "query_id": binding.query_id,
                "bucket_ordinal": binding.bucket_ordinal,
                "reaction_pt": binding.reaction_pt,
                "report_count": binding.report_count,
                "statistical_unit": binding.statistical_unit,
                "identity_stratum": binding.identity_stratum,
                "role_policy": binding.role_policy,
            }
        ).encode("utf-8")

    def publish_faers(
        self, projection: FaersAggregateExecutionProjection
    ) -> tuple[EvidenceProvenanceEnvelopeV1, ...]:
        """Publish each exact aggregate bucket after raw count replay."""

        if type(projection) is not FaersAggregateExecutionProjection:
            raise TypeError("FAERS provenance requires exact aggregate projection")
        exact = FaersAggregateExecutionProjection.model_validate(
            projection.model_dump(mode="python"), strict=True
        )
        result = exact.execution.result
        replay_parent, replay = self._source_replay_parent(
            "faers-aggregate",
            run_id=exact.run_id,
            task_id=exact.task_id,
            attempt_id=exact.attempt_id,
            query_id=result.query.query_id,
            acquisition_intent_id=exact.execution.acquisition_outcome_ref.acquisition_intent_id,
        )
        if canonical_json(exact).encode("utf-8") != replay:
            raise EvidenceProvenanceIntegrityError("FAERS source replay differs")
        envelopes: list[EvidenceProvenanceEnvelopeV1] = []
        for item in exact.bucket_evidence:
            binding = self._repository.get_faers_evidence_binding(
                run_id=exact.run_id,
                acquisition_id=exact.execution.acquisition_outcome_ref.acquisition_id,
                query_id=result.query.query_id,
                source_outcome_id=exact.execution.acquisition_outcome_ref.source_outcome_id,
                snapshot_id=result.snapshot_id,
                bucket_ordinal=item.bucket_ordinal,
            )
            if binding is None:
                raise EvidenceProvenanceIntegrityError("FAERS evidence binding is missing")
            self._verify_faers_source(binding)
            self._read_parent(binding.manifest)
            raw = self._read_parent(binding.raw)
            try:
                page = parse_count_page(raw)
            except ValueError as error:
                raise EvidenceProvenanceIntegrityError("FAERS raw count replay failed") from error
            bucket_matches = tuple(
                bucket
                for bucket in page.buckets
                if bucket.reaction_pt == binding.reaction_pt
                and bucket.report_count == binding.report_count
            )
            if len(bucket_matches) != 1:
                raise EvidenceProvenanceIntegrityError("FAERS raw bucket replay differs")
            normalized = self._faers_bucket_bytes(binding)
            if sha256_digest(normalized) != item.content_hash:
                raise EvidenceProvenanceIntegrityError("FAERS bucket content hash drift")
            record_id = derive_identity(
                "faers-bucket",
                {
                    "query_id": binding.query_id,
                    "source_outcome_id": binding.source_outcome_id,
                    "bucket_ordinal": binding.bucket_ordinal,
                    "reaction_pt": binding.reaction_pt,
                },
            )
            version = "/".join(
                (
                    binding.execution_profile_id,
                    binding.ast_schema_version,
                    binding.serializer_version,
                )
            )
            lookup = canonical_json(
                {
                    "source": "faers",
                    "acquisition_id": binding.acquisition_id,
                    "query_id": binding.query_id,
                    "source_outcome_id": binding.source_outcome_id,
                    "bucket_ordinal": binding.bucket_ordinal,
                    "locator_ref": item.locator_ref,
                }
            )
            envelopes.append(
                self._publish_envelope(
                    run_id=binding.run_id,
                    evidence_id=item.evidence_id,
                    source=SourceType.FAERS,
                    source_record_id=record_id,
                    source_version=version,
                    snapshot_id=binding.snapshot_id,
                    lookup_key=lookup,
                    retrieved_at=binding.retrieved_at_utc,
                    manifest=binding.manifest,
                    raw=binding.raw,
                    stable=None,
                    replay=replay_parent,
                    normalized=normalized,
                )
            )
        return tuple(envelopes)

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
        """Reverify anchored M1B bytes and exact PG source graph on every read."""

        if source not in (SourceType.DAILYMED, SourceType.FAERS):
            return None
        anchor = self._repository.get_evidence_provenance_anchor(
            run_id=run_id, evidence_id=evidence_id
        )
        if anchor is None:
            return None
        if (
            anchor["source"] != source.value
            or anchor["snapshot_id"] != snapshot_id
            or anchor["run_id"] != run_id
            or anchor["evidence_id"] != evidence_id
        ):
            raise EvidenceProvenanceIntegrityError("M1B provenance anchor identity drift")
        envelope_hash = anchor["envelope_hash"]
        if type(envelope_hash) is not str:
            raise EvidenceProvenanceIntegrityError("M1B provenance envelope hash is invalid")
        relative = _envelope_path(envelope_hash)
        target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            expected_size = anchor["byte_size"]
            if type(expected_size) is not int or not 1 <= expected_size <= 32_768:
                raise ValueError("M1B provenance envelope size is invalid")
            with target.open("rb") as stream:
                raw = stream.read(expected_size + 1)
            envelope = EvidenceProvenanceEnvelopeV1.from_canonical_bytes(raw)
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError("M1B provenance envelope is invalid") from error
        if (
            envelope.envelope_hash != envelope_hash
            or envelope.envelope_id != anchor["envelope_id"]
            or len(raw) != anchor["byte_size"]
            or envelope.run_id != run_id
            or envelope.evidence_id != evidence_id
            or envelope.source is not source
            or envelope.source_record_id != source_record_id
            or envelope.source_version != source_version
            or envelope.snapshot_id != snapshot_id
            or envelope.content_hash != content_hash
        ):
            raise EvidenceProvenanceIntegrityError("M1B provenance envelope binding drift")
        capture_payload, _ = self._read_capture(envelope.parent_artifacts[0])
        if (
            capture_payload["source"] != source.value
            or capture_payload["retrieved_at_utc"]
            != json.loads(canonical_json({"value": envelope.retrieved_at}))["value"]
        ):
            raise EvidenceProvenanceIntegrityError("M1B capture source or time drift")
        original_manifest = self._parent_from_payload(capture_payload["original_manifest"])
        capture_raw = self._parent_from_payload(capture_payload["raw"])
        replay_parent = self._parent_from_payload(capture_payload["source_replay"])
        normalized_parent = self._parent_from_payload(capture_payload["normalized"])
        raw_parent = self._parent_binding(envelope.parent_artifacts[1])
        envelope_normalized = self._parent_binding(envelope.parent_artifacts[2])
        if not self._same_parent(capture_raw, raw_parent) or not self._same_parent(
            normalized_parent, envelope_normalized
        ):
            raise EvidenceProvenanceIntegrityError("M1B capture parent binding drift")
        normalized = self._read_envelope_parent(envelope.parent_artifacts[2])
        lookup = self._lookup(envelope.lookup_key)
        acquisition_id = cast(str, lookup["acquisition_id"])
        query_id = cast(str, lookup["query_id"])
        source_outcome_id = lookup.get("source_outcome_id")
        if type(source_outcome_id) is not str:
            raise EvidenceProvenanceIntegrityError("M1B outcome lookup is incomplete")
        if source is SourceType.DAILYMED:
            label_version_id = lookup.get("label_version_id")
            section_id = lookup.get("section_id")
            if type(label_version_id) is not str or type(section_id) is not str:
                raise EvidenceProvenanceIntegrityError("DailyMed lookup is incomplete")
            daily_binding = self._repository.get_dailymed_evidence_binding(
                run_id=run_id,
                acquisition_id=acquisition_id,
                query_id=query_id,
                source_outcome_id=source_outcome_id,
                snapshot_id=snapshot_id,
                label_version_id=label_version_id,
                section_id=section_id,
            )
            if daily_binding is None or (
                not self._same_parent(daily_binding.manifest, original_manifest)
                or not self._same_parent(daily_binding.raw, raw_parent)
                or daily_binding.section_id != source_record_id
                or daily_binding.label_version_id != source_version
                or daily_binding.text_hash != content_hash
                or daily_binding.retrieved_at_utc != envelope.retrieved_at
            ):
                raise EvidenceProvenanceIntegrityError("DailyMed provenance source graph drift")
            self._read_parent(daily_binding.manifest)
            self._read_parent(daily_binding.raw)
            self._verify_dailymed_source(daily_binding)
            spl = self._read_parent(daily_binding.stable_spl)
            document = parse_spl_document(
                spl,
                expected_setid=daily_binding.setid,
                expected_spl_version=str(daily_binding.spl_version),
            )
            texts = tuple(
                item.text.encode("utf-8")
                for item in document.sections
                if item.section_code == daily_binding.section_code
                and item.xml_path == daily_binding.xml_path
                and item.text_start == daily_binding.text_start
                and item.text_end == daily_binding.text_end
            )
            if texts != (normalized,):
                raise EvidenceProvenanceIntegrityError("DailyMed normalized replay drift")
            stable_payload = capture_payload["stable"]
            if stable_payload is None:
                raise EvidenceProvenanceIntegrityError("DailyMed capture lacks stable SPL")
            capture_stable = self._parent_from_payload(stable_payload)
            if not self._same_parent(daily_binding.stable_spl, capture_stable):
                raise EvidenceProvenanceIntegrityError("DailyMed stable SPL capture drift")
            replay = self._read_parent(replay_parent)
            try:
                parsed_daily = DailyMedFetchExecutionProjection.model_validate_json(
                    replay, strict=False
                )
                daily_replayed = DailyMedFetchExecutionProjection.model_validate(
                    parsed_daily.model_dump(mode="python"), strict=True
                )
            except ValueError as error:
                raise EvidenceProvenanceIntegrityError(
                    "DailyMed capture replay is invalid"
                ) from error
            daily_matches = tuple(
                item
                for item in daily_replayed.section_evidence
                if item.evidence_id == evidence_id
                and item.section_id == source_record_id
                and item.content_hash == content_hash
                and item.locator_ref == lookup["locator_ref"]
            )
            if (
                canonical_json(daily_replayed).encode("utf-8") != replay
                or daily_replayed.run_id != run_id
                or daily_replayed.response.label_version_id != source_version
                or daily_replayed.response.fetch_snapshot_id != snapshot_id
                or daily_replayed.response.source_outcome_id != source_outcome_id
                or len(daily_matches) != 1
            ):
                raise EvidenceProvenanceIntegrityError("DailyMed capture replay binding drift")
        else:
            ordinal = lookup.get("bucket_ordinal")
            if type(ordinal) is not int:
                raise EvidenceProvenanceIntegrityError("FAERS bucket lookup is invalid")
            faers_binding = self._repository.get_faers_evidence_binding(
                run_id=run_id,
                acquisition_id=acquisition_id,
                query_id=query_id,
                source_outcome_id=source_outcome_id,
                snapshot_id=snapshot_id,
                bucket_ordinal=ordinal,
            )
            expected_version = (
                None
                if faers_binding is None
                else "/".join(
                    (
                        faers_binding.execution_profile_id,
                        faers_binding.ast_schema_version,
                        faers_binding.serializer_version,
                    )
                )
            )
            if faers_binding is None or (
                not self._same_parent(faers_binding.manifest, original_manifest)
                or not self._same_parent(faers_binding.raw, raw_parent)
                or self._faers_bucket_bytes(faers_binding) != normalized
                or expected_version != source_version
                or faers_binding.retrieved_at_utc != envelope.retrieved_at
            ):
                raise EvidenceProvenanceIntegrityError("FAERS provenance source graph drift")
            page = parse_count_page(self._read_parent(faers_binding.raw))
            self._verify_faers_source(faers_binding)
            if not any(
                item.reaction_pt == faers_binding.reaction_pt
                and item.report_count == faers_binding.report_count
                for item in page.buckets
            ):
                raise EvidenceProvenanceIntegrityError("FAERS normalized replay drift")
            self._read_parent(faers_binding.manifest)
            if capture_payload["stable"] is not None:
                raise EvidenceProvenanceIntegrityError("FAERS capture has a stable SPL parent")
            replay = self._read_parent(replay_parent)
            try:
                parsed_faers = FaersAggregateExecutionProjection.model_validate_json(
                    replay, strict=False
                )
                faers_replayed = FaersAggregateExecutionProjection.model_validate(
                    parsed_faers.model_dump(mode="python"), strict=True
                )
            except ValueError as error:
                raise EvidenceProvenanceIntegrityError("FAERS capture replay is invalid") from error
            faers_matches = tuple(
                item
                for item in faers_replayed.bucket_evidence
                if item.evidence_id == evidence_id
                and item.bucket_ordinal == ordinal
                and item.content_hash == content_hash
                and item.locator_ref == lookup["locator_ref"]
            )
            if (
                canonical_json(faers_replayed).encode("utf-8") != replay
                or faers_replayed.run_id != run_id
                or faers_replayed.execution.result.snapshot_id != snapshot_id
                or faers_replayed.execution.acquisition_outcome_ref.source_outcome_id
                != source_outcome_id
                or len(faers_matches) != 1
            ):
                raise EvidenceProvenanceIntegrityError("FAERS capture replay binding drift")
        return EvidenceProvenanceV1(
            envelope.evidence_id,
            envelope.source,
            envelope.source_record_id,
            envelope.source_version,
            envelope.snapshot_id,
            envelope.content_hash,
            envelope.source_url,
            envelope.lookup_key,
            envelope.retrieved_at,
            envelope.transformation_lineage,
        )

    def load_verified_material(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> VerifiedM1BEvidenceMaterial | None:
        """Expose only material re-read from the already reverified envelope parents."""

        provenance = self.load_verified_provenance(
            run_id=run_id,
            evidence_id=evidence_id,
            source=source,
            source_record_id=source_record_id,
            source_version=source_version,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
        )
        if provenance is None:
            return None
        anchor = self._repository.get_evidence_provenance_anchor(
            run_id=run_id, evidence_id=evidence_id
        )
        if anchor is None:
            raise EvidenceProvenanceIntegrityError("verified material anchor disappeared")
        envelope_hash = anchor["envelope_hash"]
        size = anchor["byte_size"]
        if type(envelope_hash) is not str or type(size) is not int or not 1 <= size <= 32_768:
            raise EvidenceProvenanceIntegrityError("verified material anchor is invalid")
        target = self._snapshots.root.joinpath(*PurePosixPath(_envelope_path(envelope_hash)).parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            with target.open("rb") as stream:
                raw = stream.read(size + 1)
            envelope = EvidenceProvenanceEnvelopeV1.from_canonical_bytes(raw)
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise EvidenceProvenanceIntegrityError("verified material envelope changed") from error
        if envelope.envelope_hash != envelope_hash or envelope.evidence_id != evidence_id:
            raise EvidenceProvenanceIntegrityError("verified material envelope binding drift")
        normalized = self._read_envelope_parent(envelope.parent_artifacts[2])
        try:
            normalized_text = normalized.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EvidenceProvenanceIntegrityError(
                "verified normalized material is not UTF-8"
            ) from error
        lookup = self._lookup(envelope.lookup_key)
        locator = lookup.get("locator_ref")
        if type(locator) is not str or not locator or len(locator) > 512:
            raise EvidenceProvenanceIntegrityError("verified material locator is invalid")
        numerical: tuple[tuple[str, str], ...] = ()
        if source is SourceType.FAERS:
            try:
                bucket = json.loads(normalized_text)
            except json.JSONDecodeError as error:
                raise EvidenceProvenanceIntegrityError(
                    "verified FAERS bucket is invalid"
                ) from error
            if type(bucket) is not dict or canonical_json(bucket) != normalized_text:
                raise EvidenceProvenanceIntegrityError("verified FAERS bucket is noncanonical")
            numerical = tuple(
                (name, str(bucket[name]))
                for name in (
                    "reaction_pt",
                    "report_count",
                    "statistical_unit",
                    "identity_stratum",
                    "role_policy",
                )
            )
        return VerifiedM1BEvidenceMaterial(
            provenance=provenance,
            locator_ref=locator,
            normalized_text=normalized_text,
            numerical_facts=numerical,
        )

    @staticmethod
    def _lookup(value: str | None) -> dict[str, object]:
        if type(value) is not str or len(value) > 2048:
            raise EvidenceProvenanceIntegrityError("M1B provenance lookup key is invalid")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise EvidenceProvenanceIntegrityError(
                "M1B provenance lookup JSON is invalid"
            ) from error
        if type(parsed) is not dict or canonical_json(parsed) != value:
            raise EvidenceProvenanceIntegrityError("M1B provenance lookup is noncanonical")
        for name in ("acquisition_id", "query_id"):
            if type(parsed.get(name)) is not str:
                raise EvidenceProvenanceIntegrityError("M1B provenance lookup is incomplete")
        return parsed

    @staticmethod
    def _parent_binding(parent: ProvenanceParentRefV1) -> M1BSourceParentBinding:
        return M1BSourceParentBinding(
            parent.artifact_id,
            parent.artifact_id,
            parent.byte_size,
            parent.relative_path,
            "manifest" if parent.kind is ProvenanceParentKind.MANIFEST else "source_response",
        )

    def _read_envelope_parent(self, parent: ProvenanceParentRefV1) -> bytes:
        binding = self._parent_binding(parent)
        return self._read_parent(binding)

    @staticmethod
    def _same_parent(binding: M1BSourceParentBinding, parent: M1BSourceParentBinding) -> bool:
        return (
            binding.artifact_id,
            binding.content_hash,
            binding.byte_size,
            binding.relative_path,
        ) == (
            parent.artifact_id,
            parent.content_hash,
            parent.byte_size,
            parent.relative_path,
        )
