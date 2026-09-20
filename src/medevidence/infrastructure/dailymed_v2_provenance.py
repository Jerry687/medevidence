"""Original-source replay authority for selected DailyMed V2 section chunks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, final

import httpx

from medevidence.connectors.dailymed.enrichment import (
    parse_packaging_page,
    project_discovery_summaries_v2,
)
from medevidence.connectors.dailymed.parsing import parse_source_native_spl_document
from medevidence.domain import SourceType, canonical_json, derive_identity, sha256_digest
from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryGroupV2,
    DailyMedEnrichmentStatus,
    DailyMedRawParentV2,
    DailyMedSelectionDecisionV2,
)
from medevidence.domain.dailymed_v2_execution import (
    DailyMedV2PackagingResult,
    DailyMedV2SectionRef,
    DailyMedV2SelectedSplResult,
)
from medevidence.domain.provenance import (
    EvidenceProvenanceEnvelopeV1,
    ProvenanceParentKind,
    ProvenanceParentRefV1,
)
from medevidence.ingestion.dailymed_v2_artifacts import (
    DAILYMED_V2_MANIFEST_CAP,
    DailyMedV2Manifest,
    DailyMedV2Member,
    replay_dailymed_v2,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.persistence import PersistenceRepository
from medevidence.persistence.dailymed_v2 import DailyMedV2RecordInput, DailyMedV2Repository
from medevidence.tools.dailymed_enrichment import (
    build_enriched_candidate,
    select_enriched_candidates,
)
from medevidence.tools.dailymed_v2_material import (
    DailyMedV2EvidenceChunk,
    build_dailymed_v2_chunks,
)
from medevidence.tools.report_document import EvidenceProvenanceV1

from .dailymed_v2_record_store import DailyMedV2RecordStore
from .dailymed_v2_source_execution import DailyMedV2SourceIntent
from .evidence_provenance import EvidenceProvenanceIntegrityError

_RUN = re.compile(r"^run:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")


@dataclass(frozen=True, slots=True)
class VerifiedDailyMedV2EvidenceMaterial:
    provenance: EvidenceProvenanceV1
    chunk: DailyMedV2EvidenceChunk


def _envelope_path(value: str) -> str:
    digest = value.removeprefix("sha256:")
    return f"m3/evidence-provenance/{digest[:2]}/{digest}.json"


def _normalized_path(value: str) -> str:
    digest = value.removeprefix("sha256:")
    return f"dailymed/normalized/sections/sha256/{digest[:2]}/{digest}.txt"


@final
class DailyMedV2ProvenanceStore:
    """Verify discovery, packaging, decision, original SPL and exact text on every load."""

    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        repository: PersistenceRepository,
        records: DailyMedV2RecordStore,
    ) -> None:
        if (
            type(snapshots) is not SnapshotStore
            or type(repository) is not PersistenceRepository
            or type(records) is not DailyMedV2RecordStore
        ):
            raise TypeError("DailyMed V2 provenance requires exact durable authorities")
        self._snapshots = snapshots
        self._repository = repository
        self._records = records

    def _read(self, relative: str, *, size: int, cap: int, digest: str) -> bytes:
        target = self._snapshots.root.joinpath(*relative.split("/"))
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if not target.is_file() or not 1 <= target.stat().st_size <= cap:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 parent is missing or oversized")
        with target.open("rb") as handle:
            raw = handle.read(cap + 1)
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if len(raw) != size or len(raw) > cap or sha256_digest(raw) != digest:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 parent bytes differ")
        return raw

    def _manifest(self, record: DailyMedV2RecordInput) -> DailyMedV2Manifest:
        run = _RUN.fullmatch(record.run_id)
        intent_digest = record.acquisition_intent_id.removeprefix("acquisition-intent:sha256:")
        if run is None or len(intent_digest) != 64:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 intent identity is invalid")
        intent_relative = (
            f"journal/{run.group(1)}/source-execution/dailymed-v2/{intent_digest}/intent.json"
        )
        intent_target = self._snapshots.root.joinpath(*intent_relative.split("/"))
        SnapshotStore._require_safe_path(self._snapshots, intent_target, allow_missing_leaf=False)
        if not intent_target.is_file() or not 1 <= intent_target.stat().st_size <= 65_536:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 START intent is missing")
        with intent_target.open("rb") as handle:
            intent_raw = handle.read(65_537)
        try:
            parsed_intent = DailyMedV2SourceIntent.model_validate_json(intent_raw, strict=False)
            intent = DailyMedV2SourceIntent.model_validate(
                parsed_intent.model_dump(mode="python"), strict=True
            )
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 START intent is invalid") from error
        if (
            intent.canonical_bytes() != intent_raw
            or intent.intent_id != record.acquisition_intent_id
            or intent.run_id != record.run_id
            or intent.attempt_id != record.attempt_id
            or intent.acquisition_id != record.acquisition_id
            or intent.query_id != record.query_id
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 START intent differs")
        digest = record.manifest_id.removeprefix("sha256:")
        relative = f"dailymed/v2/manifests/sha256/{digest[:2]}/{digest}.json"
        target = self._snapshots.root.joinpath(*relative.split("/"))
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        if not target.is_file() or not 1 <= target.stat().st_size <= DAILYMED_V2_MANIFEST_CAP:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 manifest is missing")
        with target.open("rb") as handle:
            raw = handle.read(DAILYMED_V2_MANIFEST_CAP + 1)
        if len(raw) > DAILYMED_V2_MANIFEST_CAP or sha256_digest(raw) != record.manifest_id:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 manifest bytes differ")
        manifest = DailyMedV2Manifest.from_canonical_bytes(raw)
        if (
            manifest.run_id != record.run_id
            or manifest.acquisition_id != record.acquisition_id
            or manifest.acquisition_intent_id != record.acquisition_intent_id
            or manifest.query_id != record.query_id
            or manifest.snapshot_id != record.snapshot_id
            or manifest.attempt_id != record.attempt_id
            or manifest.request_identity != intent.request_identity
            or manifest.operation != intent.operation
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 manifest context differs")
        replay_dailymed_v2(
            self._snapshots,
            manifest_id=record.manifest_id,
            expected_operation=manifest.operation,
            expected_run_id=record.run_id,
            expected_acquisition_id=record.acquisition_id,
            expected_intent_id=record.acquisition_intent_id,
            expected_query_id=record.query_id,
            expected_request_identity=manifest.request_identity,
        )
        for member in manifest.members:
            if member.kind != "dailymed_http_response":
                continue
            assert member.page_number is not None
            expected = httpx.URL(intent.request_url)
            if intent.operation in ("discovery", "packaging"):
                params = dict(expected.params)
                params["page"] = str(member.page_number)
                expected = httpx.URL(
                    f"{expected.scheme}://{expected.host}{expected.path}",
                    params=tuple(sorted(params.items())),
                )
            if member.request_url != str(expected) or member.final_url != str(expected):
                raise EvidenceProvenanceIntegrityError("DailyMed V2 raw URL differs from START")
        graph = DailyMedV2Repository(self._repository).load_source_graph(
            run_id=record.run_id,
            acquisition_id=record.acquisition_id,
            query_id=record.query_id,
            snapshot_id=record.snapshot_id,
        )
        if graph is None:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 source SQL graph is missing")
        acquisition = graph["acquisition"]
        snapshot = graph["snapshot"]
        outcome = graph["outcome"]
        if (
            not isinstance(acquisition, dict)
            or not isinstance(snapshot, dict)
            or not isinstance(outcome, dict)
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 source SQL row type differs")
        operation = {
            "discovery": "search",
            "packaging": "packaging",
            "selected_spl": "fetch",
        }[manifest.operation]
        if (
            acquisition.get("acquisition_intent_id") != record.acquisition_intent_id
            or acquisition.get("attempt_id") != record.attempt_id
            or acquisition.get("operation") != operation
            or acquisition.get("acquisition_ordinal") != manifest.acquisition_ordinal
            or acquisition.get("started_at_utc") != manifest.started_at_utc
            or acquisition.get("completed_at_utc") != manifest.completed_at_utc
            or acquisition.get("request_identity") != manifest.request_identity
            or snapshot.get("manifest_artifact_id") != manifest.manifest_id
            or snapshot.get("acquisition_intent_id") != record.acquisition_intent_id
            or snapshot.get("retrieved_at_utc") != manifest.completed_at_utc
            or outcome.get("acquisition_intent_id") != record.acquisition_intent_id
            or outcome.get("operation") != operation
            or outcome.get("execution_status") != manifest.source_outcome.execution_status.value
            or outcome.get("coverage_status") != manifest.source_outcome.coverage_status.value
            or outcome.get("result_status") != manifest.source_outcome.result_status.value
            or outcome.get("valid_result_count") != manifest.source_outcome.valid_result_count
            or outcome.get("pages_completed") != manifest.source_outcome.pages_completed
            or outcome.get("truncated") != manifest.source_outcome.truncated
            or outcome.get("warning_codes") != list(manifest.source_outcome.warning_codes)
            or outcome.get("failure_id") != manifest.source_outcome.failure_id
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 source SQL context differs")
        members = graph["membership"]
        raw_members = tuple(
            item for item in manifest.members if item.kind == "dailymed_http_response"
        )
        if not isinstance(members, tuple) or len(members) != len(raw_members):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 SQL response membership differs")
        for member, row in zip(raw_members, members, strict=True):
            if not isinstance(row, dict) or (
                row.get("ordinal") != member.ordinal
                or row.get("link_id") != member.link_id
                or row.get("artifact_id") != member.artifact_id
                or row.get("content_hash") != member.content_hash
                or row.get("relative_path") != member.relative_path
                or row.get("byte_size") != member.byte_size
                or row.get("media_type") != member.media_type
                or row.get("http_status") != member.http_status
                or row.get("observed_at_utc") != member.observed_at_utc
                or row.get("body_complete") != member.body_complete
                or row.get("termination_reason") != member.termination_reason
                or row.get("page_number") != member.page_number
                or row.get("attempt_count") != member.attempt_count
                or row.get("request_url") != member.request_url
                or row.get("final_url") != member.final_url
            ):
                raise EvidenceProvenanceIntegrityError("DailyMed V2 SQL member differs")
        artifacts = graph["artifacts"]
        if not isinstance(artifacts, tuple):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 SQL artifacts are invalid")
        artifact_map = {
            item.get("artifact_id"): item for item in artifacts if isinstance(item, dict)
        }
        manifest_artifact = artifact_map.get(manifest.manifest_id)
        if (
            not isinstance(manifest_artifact, dict)
            or manifest_artifact.get("artifact_kind") != "dailymed_v2_manifest"
            or manifest_artifact.get("content_hash") != manifest.manifest_id
            or manifest_artifact.get("byte_size") != len(manifest.canonical_bytes())
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 SQL manifest artifact differs")
        for member in raw_members:
            artifact = artifact_map.get(member.artifact_id)
            if (
                not isinstance(artifact, dict)
                or artifact.get("artifact_kind") != "dailymed_http_response"
                or artifact.get("relative_storage_label") != member.relative_path
                or artifact.get("content_hash") != member.content_hash
                or artifact.get("byte_size") != member.byte_size
            ):
                raise EvidenceProvenanceIntegrityError("DailyMed V2 SQL raw artifact differs")
        return manifest

    @staticmethod
    def _expected_parent(
        manifest: DailyMedV2Manifest,
        ordinal: int,
        *,
        kind: Literal["discovery_json", "packaging_json"],
    ) -> DailyMedRawParentV2:
        if not 0 <= ordinal < len(manifest.members):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 raw parent ordinal is missing")
        member = manifest.members[ordinal]
        if member.kind != "dailymed_http_response" or not member.body_complete:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 raw parent is incomplete")
        return DailyMedRawParentV2(
            kind=kind,
            run_id=manifest.run_id,
            attempt_id=manifest.attempt_id,
            acquisition_id=manifest.acquisition_id,
            acquisition_ordinal=manifest.acquisition_ordinal,
            acquisition_intent_id=manifest.acquisition_intent_id,
            query_id=manifest.query_id,
            snapshot_id=manifest.snapshot_id,
            manifest_id=manifest.manifest_id,
            member_ordinal=member.ordinal,
            link_id=member.link_id,
            raw_artifact_id=member.artifact_id,
            raw_content_hash=member.content_hash,
            byte_size=member.byte_size,
        )

    def _member_bytes(self, member: DailyMedV2Member) -> bytes:
        return self._read(
            member.relative_path,
            size=member.byte_size,
            cap=5_242_880,
            digest=member.content_hash,
        )

    def _chain(
        self, chunk: DailyMedV2EvidenceChunk
    ) -> tuple[
        DailyMedV2Manifest,
        DailyMedV2Member,
        DailyMedV2RecordInput,
        DailyMedV2RecordInput,
        DailyMedV2RecordInput,
        DailyMedV2RecordInput,
    ]:
        chunk_loaded = self._records.load_chunk_evidence(
            run_id=chunk.run_id,
            evidence_id=chunk.evidence_id,
        )
        if (
            chunk_loaded is None
            or type(chunk_loaded.payload) is not DailyMedV2EvidenceChunk
            or chunk_loaded.payload != chunk
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 chunk record is missing")
        selected_loaded = self._records.load_slot(
            run_id=chunk.run_id,
            attempt_id=chunk_loaded.record.attempt_id,
            record_kind="selected_spl",
            query_id=chunk_loaded.record.query_id,
        )
        if (
            selected_loaded is None
            or type(selected_loaded.payload) is not DailyMedV2SelectedSplResult
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 selected record is missing")
        selected_result = selected_loaded.payload
        selected = selected_result.selected
        if selected is None or chunk.evidence_id not in selected.evidence_chunk_ids:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 chunk is not selected")
        selected_manifest = self._manifest(selected_loaded.record)
        if (
            selected_manifest.operation != "selected_spl"
            or selected_manifest.source_outcome != selected_result.source_outcome
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 selected source outcome differs")
        stable = tuple(
            item for item in selected_manifest.members if item.kind == "dailymed_spl_xml"
        )
        raw = tuple(
            item
            for item in selected_manifest.members
            if item.kind == "dailymed_http_response"
            and item.http_status == 200
            and item.body_complete
        )
        if len(stable) != 1 or len(raw) != 1 or stable[0].content_hash != selected.stable_spl_hash:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 selected raw/stable pair differs")
        raw_spl = self._member_bytes(stable[0])
        if self._member_bytes(raw[0]) != raw_spl:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 current raw/stable bytes differ")
        parsed = parse_source_native_spl_document(
            raw_spl,
            expected_setid=selected.candidate.summary.setid,
            expected_spl_version=selected.candidate.summary.current_spl_version,
        )
        if selected.section_refs != tuple(
            DailyMedV2SectionRef.from_section(item) for item in parsed.sections
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 source-native refs differ")
        expected_source_version = derive_identity(
            "dailymed-v2-label-version",
            {
                "setid": selected.candidate.summary.setid,
                "spl_version": selected.candidate.summary.current_spl_version,
                "stable_spl_hash": selected.stable_spl_hash,
            },
        )
        if chunk.source_version != expected_source_version:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 source version differs")
        expected_chunks = build_dailymed_v2_chunks(
            run_id=chunk.run_id,
            snapshot_id=selected.fetch_snapshot_id,
            source_version=chunk.source_version,
            sections=parsed.sections,
        )
        if (
            chunk not in expected_chunks
            or tuple(item.evidence_id for item in expected_chunks) != selected.evidence_chunk_ids
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 section slice differs from SPL")
        candidate = selected.candidate
        summary = candidate.summary
        discovery_loaded = self._records.load_slot(
            run_id=chunk.run_id,
            attempt_id=selected.attempt_id,
            record_kind="discovery",
            query_id=selected.discovery_query_id,
        )
        packaging_loaded = self._records.load_slot(
            run_id=chunk.run_id,
            attempt_id=selected.attempt_id,
            record_kind="packaging",
            query_id=candidate.enrichment_parent.query_id,
        )
        decision_loaded = self._records.load_slot(
            run_id=chunk.run_id,
            attempt_id=selected.attempt_id,
            record_kind="decision",
            query_id=selected.discovery_query_id,
        )
        if (
            discovery_loaded is None
            or type(discovery_loaded.payload) is not DailyMedDiscoveryGroupV2
            or packaging_loaded is None
            or type(packaging_loaded.payload) is not DailyMedV2PackagingResult
            or decision_loaded is None
            or type(decision_loaded.payload) is not DailyMedSelectionDecisionV2
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 selection ancestry is missing")
        group = discovery_loaded.payload
        packaging = packaging_loaded.payload
        decision = decision_loaded.payload
        discovery_manifest = self._manifest(discovery_loaded.record)
        packaging_manifest = self._manifest(packaging_loaded.record)
        if (
            discovery_manifest.operation != "discovery"
            or packaging_manifest.operation != "packaging"
            or group.summaries != (summary,)
            or group.outcome != discovery_manifest.source_outcome
            or packaging.source_outcome != packaging_manifest.source_outcome
            or packaging.execution is None
            or packaging.execution.parent != candidate.enrichment_parent
            or build_enriched_candidate(summary, packaging.execution) != candidate
            or select_enriched_candidates((group,), 0, (candidate,)) != decision
            or decision != selected.decision
            or decision.status is not DailyMedEnrichmentStatus.SELECTED
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 selection ancestry differs")
        parent = summary.parent
        if parent != self._expected_parent(
            discovery_manifest, parent.member_ordinal, kind="discovery_json"
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 discovery parent differs")
        discovery_raw = self._member_bytes(discovery_manifest.members[parent.member_ordinal])
        if summary not in project_discovery_summaries_v2(
            discovery_raw,
            parent=parent,
            expected_page=discovery_manifest.members[parent.member_ordinal].page_number or 1,
            first_ordinal=0,
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 discovery summary is not raw")
        package_parent = candidate.enrichment_parent
        if package_parent != self._expected_parent(
            packaging_manifest, package_parent.member_ordinal, kind="packaging_json"
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 packaging parent differs")
        package_raw = self._member_bytes(packaging_manifest.members[package_parent.member_ordinal])
        page = parse_packaging_page(
            package_raw,
            expected_setid=summary.setid,
            expected_spl_version=summary.current_spl_version,
            expected_page=1,
        )
        if page.products != packaging.execution.products or page.next_page is not None:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 packaging products are not raw")
        return (
            selected_manifest,
            raw[0],
            selected_loaded.record,
            discovery_loaded.record,
            packaging_loaded.record,
            decision_loaded.record,
        )

    def publish(self, chunk: DailyMedV2EvidenceChunk) -> EvidenceProvenanceV1:
        """Publish exact normalized slice and anchored ancestry after raw replay."""

        if type(chunk) is not DailyMedV2EvidenceChunk:
            raise TypeError("DailyMed V2 provenance requires exact chunk")
        (
            manifest,
            raw_member,
            selected_record,
            discovery_record,
            packaging_record,
            decision_record,
        ) = self._chain(chunk)
        normalized = chunk.chunk_text.encode("utf-8")
        normalized_path = _normalized_path(chunk.chunk_hash)
        target = self._snapshots.root.joinpath(*normalized_path.split("/"))
        if self._snapshots.has_writer_lock:
            SnapshotStore.publish_bytes(
                self._snapshots, normalized_path, normalized, artifact_class="journal"
            )
        else:
            with SnapshotStore.writer(self._snapshots):
                SnapshotStore.publish_bytes(
                    self._snapshots, normalized_path, normalized, artifact_class="journal"
                )
        SnapshotStore._require_safe_path(self._snapshots, target, allow_missing_leaf=False)
        chunk_loaded = self._records.load_chunk_evidence(
            run_id=chunk.run_id, evidence_id=chunk.evidence_id
        )
        if chunk_loaded is None or chunk_loaded.payload != chunk:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 chunk record disappeared")
        lookup = canonical_json(
            {
                "schema_version": "m3.dailymed-v2-lookup.v1",
                "selected_record_id": selected_record.record_id,
                "discovery_record_id": discovery_record.record_id,
                "packaging_record_id": packaging_record.record_id,
                "decision_record_id": decision_record.record_id,
                "chunk_record_id": chunk_loaded.record.record_id,
                "locator_ref": chunk.locator_ref,
            }
        )
        digest = manifest.manifest_id.removeprefix("sha256:")
        manifest_path = f"dailymed/v2/manifests/sha256/{digest[:2]}/{digest}.json"
        parents = (
            ProvenanceParentRefV1(
                kind=ProvenanceParentKind.MANIFEST,
                artifact_id=manifest.manifest_id,
                relative_path=manifest_path,
                byte_size=len(manifest.canonical_bytes()),
            ),
            ProvenanceParentRefV1(
                kind=ProvenanceParentKind.RAW,
                artifact_id=raw_member.artifact_id,
                relative_path=raw_member.relative_path,
                byte_size=raw_member.byte_size,
            ),
            ProvenanceParentRefV1(
                kind=ProvenanceParentKind.NORMALIZED,
                artifact_id=chunk.chunk_hash,
                relative_path=normalized_path,
                byte_size=len(normalized),
            ),
        )
        lineage = tuple(
            dict.fromkeys(
                (
                    raw_member.artifact_id,
                    discovery_record.payload_hash,
                    packaging_record.payload_hash,
                    decision_record.payload_hash,
                    selected_record.payload_hash,
                    chunk.chunk_hash,
                )
            )
        )
        envelope = EvidenceProvenanceEnvelopeV1.create(
            run_id=chunk.run_id,
            evidence_id=chunk.evidence_id,
            source=SourceType.DAILYMED,
            source_record_id=chunk.source_record_id,
            source_version=chunk.source_version,
            snapshot_id=chunk.snapshot_id,
            content_hash=chunk.chunk_hash,
            source_url=None,
            lookup_key=lookup,
            retrieved_at=manifest.completed_at_utc,
            transformation_lineage=lineage,
            parent_artifacts=parents,
        )
        data = envelope.canonical_bytes()
        envelope_path = _envelope_path(envelope.envelope_hash)
        if self._snapshots.has_writer_lock:
            SnapshotStore.publish_bytes(
                self._snapshots, envelope_path, data, artifact_class="journal"
            )
        else:
            with SnapshotStore.writer(self._snapshots):
                SnapshotStore.publish_bytes(
                    self._snapshots, envelope_path, data, artifact_class="journal"
                )
        self._repository.insert_or_verify_evidence_provenance(envelope)
        verified = self.load_verified_provenance(
            run_id=envelope.run_id,
            evidence_id=envelope.evidence_id,
            source=envelope.source,
            source_record_id=envelope.source_record_id,
            source_version=envelope.source_version,
            snapshot_id=envelope.snapshot_id,
            content_hash=envelope.content_hash,
        )
        if verified is None:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 published proof readback failed")
        return verified

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
        if source is not SourceType.DAILYMED or not source_record_id.startswith(
            "dailymed-v2-section-chunk:sha256:"
        ):
            return None
        anchor = self._repository.get_evidence_provenance_anchor(
            run_id=run_id, evidence_id=evidence_id
        )
        if anchor is None:
            return None
        digest = anchor.get("envelope_hash")
        size = anchor.get("byte_size")
        if type(digest) is not str or type(size) is not int or not 1 <= size <= 32_768:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 anchor is invalid")
        raw = self._read(_envelope_path(digest), size=size, cap=32_768, digest=digest)
        try:
            envelope = EvidenceProvenanceEnvelopeV1.from_canonical_bytes(raw)
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 envelope is invalid") from error
        if (
            anchor.get("envelope_id") != envelope.envelope_id
            or anchor.get("run_id") != run_id
            or anchor.get("evidence_id") != evidence_id
            or anchor.get("source") != source.value
            or anchor.get("snapshot_id") != snapshot_id
            or envelope.run_id != run_id
            or envelope.evidence_id != evidence_id
            or envelope.source is not source
            or envelope.source_record_id != source_record_id
            or envelope.source_version != source_version
            or envelope.snapshot_id != snapshot_id
            or envelope.content_hash != content_hash
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 envelope binding differs")
        try:
            lookup = json.loads(envelope.lookup_key or "")
        except ValueError as error:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 lookup is invalid") from error
        if (
            type(lookup) is not dict
            or set(lookup)
            != {
                "schema_version",
                "selected_record_id",
                "discovery_record_id",
                "packaging_record_id",
                "decision_record_id",
                "chunk_record_id",
                "locator_ref",
            }
            or lookup["schema_version"] != "m3.dailymed-v2-lookup.v1"
            or canonical_json(lookup) != envelope.lookup_key
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 lookup shape differs")
        chunk_loaded = self._records.load_chunk_evidence(run_id=run_id, evidence_id=evidence_id)
        if (
            chunk_loaded is None
            or chunk_loaded.record.record_id != lookup["chunk_record_id"]
            or type(chunk_loaded.payload) is not DailyMedV2EvidenceChunk
            or chunk_loaded.payload.source_record_id != source_record_id
            or chunk_loaded.payload.source_version != source_version
            or chunk_loaded.payload.snapshot_id != snapshot_id
            or chunk_loaded.payload.chunk_hash != content_hash
            or chunk_loaded.payload.locator_ref != lookup["locator_ref"]
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 chunk lookup differs")
        chunk = chunk_loaded.payload
        (
            manifest,
            raw_member,
            selected_record,
            discovery_record,
            packaging_record,
            decision_record,
        ) = self._chain(chunk)
        if (
            lookup["selected_record_id"] != selected_record.record_id
            or lookup["discovery_record_id"] != discovery_record.record_id
            or lookup["packaging_record_id"] != packaging_record.record_id
            or lookup["decision_record_id"] != decision_record.record_id
            or envelope.retrieved_at != manifest.completed_at_utc
            or envelope.source_url is not None
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 ancestry lookup differs")
        digest_part = manifest.manifest_id.removeprefix("sha256:")
        expected_parents = (
            (
                manifest.manifest_id,
                f"dailymed/v2/manifests/sha256/{digest_part[:2]}/{digest_part}.json",
                len(manifest.canonical_bytes()),
            ),
            (raw_member.artifact_id, raw_member.relative_path, raw_member.byte_size),
            (
                chunk.chunk_hash,
                _normalized_path(chunk.chunk_hash),
                len(chunk.chunk_text.encode("utf-8")),
            ),
        )
        if (
            tuple(
                (item.artifact_id, item.relative_path, item.byte_size)
                for item in envelope.parent_artifacts
            )
            != expected_parents
        ):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 envelope parents differ")
        normalized = self._read(
            expected_parents[2][1],
            size=expected_parents[2][2],
            cap=5_242_880,
            digest=chunk.chunk_hash,
        )
        if normalized != chunk.chunk_text.encode("utf-8"):
            raise EvidenceProvenanceIntegrityError("DailyMed V2 normalized slice differs")
        expected_lineage = tuple(
            dict.fromkeys(
                (
                    raw_member.artifact_id,
                    discovery_record.payload_hash,
                    packaging_record.payload_hash,
                    decision_record.payload_hash,
                    selected_record.payload_hash,
                    chunk.chunk_hash,
                )
            )
        )
        if envelope.transformation_lineage != expected_lineage:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 transformation lineage differs")
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
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> VerifiedDailyMedV2EvidenceMaterial | None:
        proof = self.load_verified_provenance(
            run_id=run_id,
            evidence_id=evidence_id,
            source=SourceType.DAILYMED,
            source_record_id=source_record_id,
            source_version=source_version,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
        )
        if proof is None:
            return None
        stored = self._records.load_chunk_evidence(run_id=run_id, evidence_id=evidence_id)
        if stored is None or type(stored.payload) is not DailyMedV2EvidenceChunk:
            raise EvidenceProvenanceIntegrityError("DailyMed V2 verified chunk disappeared")
        return VerifiedDailyMedV2EvidenceMaterial(proof, stored.payload)
