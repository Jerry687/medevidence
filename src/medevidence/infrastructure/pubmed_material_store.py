"""Durable PubMed material selection with raw-source and snapshot rederivation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import final

from pydantic import TypeAdapter

from medevidence.connectors.pubmed.client import reconcile_retained_fetch_response
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    PublicationRecord,
    ResearchScope,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.domain.catalogs import LOCAL_RESEARCH_CATALOG_HASH
from medevidence.domain.identifiers import RunId
from medevidence.ingestion.artifacts import SnapshotManifest
from medevidence.ingestion.snapshots import (
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.persistence.repositories import PersistenceRepository
from medevidence.persistence.research_jobs import ResearchJobRepository
from medevidence.tools.contracts import ResolvedConceptCatalog
from medevidence.tools.ports import (
    PersistedPublicationBinding,
    PersistedPublicationLineageEdge,
    PubMedSearchProgressRecord,
)
from medevidence.tools.pubmed import build_pubmed_query, query_identity
from medevidence.tools.pubmed_material import PubMedMaterialSelection, select_pubmed_material
from medevidence.tools.pubmed_material_ports import VerifiedPubMedMaterialPort
from medevidence.tools.report_validation import _primitive, canonical_evidence_id
from medevidence.tools.research import _with_report_outcome

from .evidence_provenance import (
    EvidenceProvenanceIntegrityError,
    PubMedSourceCaptureProof,
    VerifiedEvidenceProvenanceStore,
)

_SCHEMA = "m3.pubmed-material-selection.v1"
_MAX_JOURNAL_BYTES = 2048
_MAX_PARENT_BYTES = 5_242_880
_CONFIG = PubMedConnectorConfig.m1a_constrained_v1()


class PubMedMaterialStoreError(ValueError):
    """The recorded material or one source parent is unavailable or inconsistent."""


def _identity(
    *, run_id: str, scope_id: str, publication_version_id: str, snapshot_id: str
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "scope_id": scope_id,
        "publication_version_id": publication_version_id,
        "snapshot_id": snapshot_id,
    }


def _relative_path(identity: dict[str, str]) -> str:
    digest = sha256_digest(canonical_json(identity)).removeprefix("sha256:")
    return f"m3/pubmed-material/{digest[:2]}/{digest}.json"


def _selection_hash(selection: PubMedMaterialSelection) -> str:
    return sha256_digest(
        canonical_json(
            {
                "evidence": None if selection.evidence is None else _primitive(selection.evidence),
                "citation": (
                    None
                    if selection.citation is None
                    else selection.citation.model_dump(mode="json")
                ),
                "exclusion": None if selection.exclusion is None else selection.exclusion.value,
                "limitations": selection.limitations,
                "source_reference": _primitive(selection.source_reference),
            }
        )
    )


def _decode_record(raw: bytes, identity: dict[str, str]) -> str:
    if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_JOURNAL_BYTES:
        raise PubMedMaterialStoreError("material journal size is invalid")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PubMedMaterialStoreError("material journal JSON is invalid") from error
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "identity", "selection_hash"}
        or value["schema_version"] != _SCHEMA
        or value["identity"] != identity
        or type(value["selection_hash"]) is not str
        or canonical_json(value).encode("utf-8") != raw
    ):
        raise PubMedMaterialStoreError("material journal identity or bytes differ")
    return value["selection_hash"]


def _check_source_reference(
    selected: PubMedMaterialSelection,
    publication: PublicationRecord,
    binding: PersistedPublicationBinding,
    run_id: str,
) -> None:
    reference = selected.source_reference
    if (
        reference.evidence_id != canonical_evidence_id(reference)
        or reference.authorized_run_id != run_id
        or reference.source is not SourceType.PUBMED
        or reference.source_record_id != publication.pmid
        or reference.source_version != publication.publication_version_id
        or reference.snapshot_id != binding.snapshot_id
        or reference.content_hash != publication.content_hash
        or reference.numerical_facts
    ):
        raise PubMedMaterialStoreError("source reference identity or authority differs")
    if selected.evidence is not None:
        if (
            selected.source_reference != selected.evidence
            or selected.citation is None
            or selected.exclusion is not None
        ):
            raise PubMedMaterialStoreError("included material reference differs")
        return
    title_locator = (
        f"m3.pubmed.record-metadata.v1/{publication.publication_version_id}/"
        f"normalized-title/0:{len(publication.title)}"
    )
    if (
        selected.citation is not None
        or selected.exclusion is None
        or reference.normalized_excerpt != publication.title
        or reference.locators != (title_locator,)
        or reference.permitted_claim_classes
        or reference.permitted_inference_uses
    ):
        raise PubMedMaterialStoreError("excluded material is not exact metadata-only title")


@final
class SnapshotPubMedMaterialStore(VerifiedPubMedMaterialPort):
    """Persist a selection hash, then rederive source material on every read."""

    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        repository: PersistenceRepository,
        provenance: VerifiedEvidenceProvenanceStore,
        local_jobs: ResearchJobRepository | None = None,
    ) -> None:
        if (
            type(snapshots) is not SnapshotStore
            or type(provenance) is not VerifiedEvidenceProvenanceStore
        ):
            raise TypeError("PubMed material requires exact snapshot and provenance stores")
        self._snapshots = snapshots
        self._repository = repository
        self._provenance = provenance
        if local_jobs is not None and type(local_jobs) is not ResearchJobRepository:
            raise TypeError("local PubMed material requires the exact job registry")
        self._local_jobs = local_jobs

    def _read_parent(self, relative: str, digest: str) -> bytes:
        target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= _MAX_PARENT_BYTES:
                raise PubMedMaterialStoreError("source parent byte bound is invalid")
            self._snapshots._verify_file(target, digest.removeprefix("sha256:"), size)
            with target.open("rb") as handle:
                raw = handle.read(size + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            if len(raw) != size or sha256_digest(raw) != digest:
                raise PubMedMaterialStoreError("source parent changed during read")
            return raw
        except (OSError, ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise PubMedMaterialStoreError("source parent is unavailable or invalid") from error

    def _replay_publication(
        self,
        *,
        run_id: str,
        publication_version_id: str,
        snapshot_id: str,
        expected_query_id: str,
    ) -> tuple[PublicationRecord, PersistedPublicationBinding]:
        metadata = self._repository.get_snapshot(snapshot_id)
        if metadata is None or metadata.attempt is None:
            raise PubMedMaterialStoreError("source snapshot or run attempt is unavailable")
        if (
            metadata.attempt["run_id"] != run_id
            or metadata.attempt["manifest_id"] != snapshot_id
            or metadata.attempt["acquisition_intent_id"]
            != metadata.snapshot["acquisition_intent_id"]
            or metadata.snapshot["source"] != SourceType.PUBMED.value
            or metadata.snapshot["snapshot_id"] != snapshot_id
            or metadata.snapshot["manifest_artifact_id"] != snapshot_id
            or metadata.snapshot["manifest_content_hash"] != snapshot_id
            or metadata.snapshot["request_identity"] != expected_query_id
        ):
            raise PubMedMaterialStoreError("source snapshot belongs to another run")
        matches = tuple(
            row
            for row in metadata.publications
            if row["publication_version_id"] == publication_version_id
        )
        if len(matches) != 1:
            raise PubMedMaterialStoreError("publication version is not a unique snapshot member")
        row = matches[0]
        try:
            PersistenceRepository._validate_publication(row)
        except ValueError as error:
            raise PubMedMaterialStoreError("persisted publication row is invalid") from error
        membership = tuple(
            item
            for item in metadata.publication_memberships
            if item["publication_version_id"] == publication_version_id
            and item["pmid"] == row["pmid"]
            and item["publication_content_hash"] == row["content_hash"]
        )
        if len(membership) != 1 or row["publication_artifact_id"] != row["content_hash"]:
            raise PubMedMaterialStoreError("publication membership or artifact differs")
        manifest_digest = snapshot_id.removeprefix("sha256:")
        manifest_bytes = self._read_parent(
            f"pubmed/manifests/sha256/{manifest_digest[:2]}/{manifest_digest}.json", snapshot_id
        )
        try:
            manifest = SnapshotManifest.from_json_bytes(manifest_bytes)
        except ValueError as error:
            raise PubMedMaterialStoreError("source manifest is invalid") from error
        if (
            manifest.manifest_id != snapshot_id
            or manifest.source_type != SourceType.PUBMED.value
            or manifest.acquisition_intent_id != metadata.snapshot["acquisition_intent_id"]
            or manifest.request_identity != metadata.snapshot["request_identity"]
            or manifest.started_at_utc != metadata.snapshot["started_at_utc"]
            or manifest.completed_at_utc != metadata.snapshot["completed_at_utc"]
            or manifest.record_count != metadata.snapshot["record_count"]
            or manifest.execution_status.value != metadata.snapshot["execution_status"]
            or manifest.coverage_status.value != metadata.snapshot["coverage_status"]
            or manifest.result_status.value != metadata.snapshot["result_status"]
            or manifest.pages_completed != metadata.snapshot["pages_completed"]
            or manifest.truncated != metadata.snapshot["truncated"]
            or tuple(item["warning_code"] for item in metadata.warnings) != manifest.warning_codes
            or len(manifest.files) != 1
            or len(metadata.files) != 1
        ):
            raise PubMedMaterialStoreError("source manifest differs from persisted snapshot")
        raw_ref = manifest.files[0]
        raw_meta = metadata.files[0]
        raw_digest = raw_ref.artifact_id.removeprefix("sha256:")
        if (
            raw_ref.artifact_id != raw_meta["raw_artifact_id"]
            or raw_ref.relative_path != f"pubmed/sha256/{raw_digest[:2]}/{raw_digest}.bin"
            or raw_ref.relative_path != raw_meta["relative_storage_path"]
            or raw_ref.byte_size != raw_meta["byte_size"]
            or raw_meta["raw_content_hash"] != raw_ref.artifact_id
            or raw_ref.http_status != 200
            or raw_ref.body_complete is not True
        ):
            raise PubMedMaterialStoreError("raw source membership differs")
        raw = self._read_parent(raw_ref.relative_path, raw_ref.artifact_id)
        normalized_digest = row["content_hash"].removeprefix("sha256:")
        normalized = self._read_parent(
            f"pubmed/publications/sha256/{normalized_digest[:2]}/{normalized_digest}.json",
            row["content_hash"],
        )
        if normalized != canonical_json(row["version_payload"]).encode("utf-8"):
            raise PubMedMaterialStoreError("normalized parent differs from publication row")
        edges = {
            (item["lineage_type"], item["parent_artifact_id"], item["child_artifact_id"])
            for item in metadata.lineage
        }
        if ("manifest_to_raw_response", snapshot_id, raw_ref.artifact_id) not in edges or (
            "publication_to_manifest",
            row["content_hash"],
            snapshot_id,
        ) not in edges:
            raise PubMedMaterialStoreError("source parent lineage differs")
        retrieved = row["status_retrieved_at_utc"]
        if (
            type(retrieved) is not datetime
            or retrieved.tzinfo is None
            or retrieved.utcoffset() is None
            or not manifest.started_at_utc <= retrieved <= manifest.completed_at_utc
        ):
            raise PubMedMaterialStoreError("publication retrieval timestamp is invalid")
        try:
            replay = reconcile_retained_fetch_response(
                raw,
                (row["pmid"],),
                query_id=metadata.snapshot["request_identity"],
                retrieved_at=retrieved.astimezone(UTC),
                config=_CONFIG,
            )
        except ValueError as error:
            raise PubMedMaterialStoreError("retained PubMed raw replay is invalid") from error
        if len(replay.publications) != 1:
            raise PubMedMaterialStoreError("retained raw does not contain one publication")
        raw_publication = replay.publications[0]
        if (
            raw_publication.publication_version_id != publication_version_id
            or raw_publication.content_hash != row["content_hash"]
            or canonical_json(raw_publication.version_payload()).encode("utf-8") != normalized
        ):
            raise PubMedMaterialStoreError("raw and normalized publication content differ")
        binding = PersistedPublicationBinding(
            pmid=row["pmid"],
            publication_version_id=publication_version_id,
            publication_artifact_id=row["content_hash"],
            snapshot_id=snapshot_id,
            manifest_id=snapshot_id,
            artifact_ids=tuple(sorted((row["content_hash"], snapshot_id))),
            lineage_edges=(
                PersistedPublicationLineageEdge(
                    parent_artifact_id=row["content_hash"], child_artifact_id=snapshot_id
                ),
            ),
        )
        bounds = ExecutionBounds(
            max_query_characters=_CONFIG.max_query_characters,
            max_pages=_CONFIG.max_pages,
            max_records=_CONFIG.max_records,
            max_payload_bytes=_CONFIG.max_payload_bytes,
            max_total_seconds=_CONFIG.total_deadline_seconds,
        )
        outcome = SourceOutcome(
            source=SourceType.PUBMED,
            query_id=metadata.snapshot["request_identity"],
            execution_status=ExecutionStatus(metadata.snapshot["execution_status"]),
            coverage_status=CoverageStatus(metadata.snapshot["coverage_status"]),
            result_status=ResultStatus(metadata.snapshot["result_status"]),
            configured_bounds=bounds,
            valid_result_count=metadata.snapshot["record_count"],
            pages_completed=metadata.snapshot["pages_completed"],
            truncated=metadata.snapshot["truncated"],
            warning_codes=manifest.warning_codes,
            failure_id=None,
        )
        publication = _with_report_outcome(raw_publication, outcome)
        provenance = publication.provenance.model_copy(
            update={
                "snapshot_id": snapshot_id,
                "artifact_ids": binding.artifact_ids,
                "transformation_lineage": (row["content_hash"], snapshot_id),
            }
        )
        publication = PublicationRecord.model_validate(
            {**publication.model_dump(mode="python"), "provenance": provenance}, strict=True
        )
        return publication, binding

    def _selection(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        publication_version_id: str,
        snapshot_id: str,
    ) -> tuple[PubMedMaterialSelection, PublicationRecord, PersistedPublicationBinding]:
        try:
            expected_query_id = self._verify_run_scope(
                run_id=run_id,
                scope=scope,
                catalog=catalog,
                snapshot_id=snapshot_id,
                publication_version_id=publication_version_id,
            )
            publication, binding = self._replay_publication(
                run_id=run_id,
                publication_version_id=publication_version_id,
                snapshot_id=snapshot_id,
                expected_query_id=expected_query_id,
            )
        except PubMedMaterialStoreError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise PubMedMaterialStoreError("persisted source replay is invalid") from error
        try:
            selected = select_pubmed_material(
                run_id=run_id,
                scope=scope,
                catalog=catalog,
                publication=publication,
                binding=binding,
            )
        except ValueError as error:
            raise PubMedMaterialStoreError(
                "source material selection cannot be rederived"
            ) from error
        _check_source_reference(selected, publication, binding, run_id)
        return selected, publication, binding

    def _verify_run_scope(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        snapshot_id: str,
        publication_version_id: str | None = None,
    ) -> str:
        if self._local_jobs is not None:
            return self._verify_local_job_scope(
                run_id=run_id,
                scope=scope,
                catalog=catalog,
                snapshot_id=snapshot_id,
                publication_version_id=publication_version_id,
            )
        metadata = self._repository.get_run(run_id)
        if metadata is None:
            raise PubMedMaterialStoreError("persisted research run is unavailable")
        run = metadata.run
        dates = (
            (None, None)
            if scope.date_range is None
            else (scope.date_range.start_date, scope.date_range.end_date)
        )
        try:
            expected_query = build_pubmed_query(scope, catalog)
        except ValueError as error:
            raise PubMedMaterialStoreError("local catalog query is invalid") from error
        if (
            run["run_id"] != run_id
            or run["source"] != SourceType.PUBMED.value
            or run["scope_id"] != scope.scope_id
            or run["catalog_version"] != catalog.catalog_version
            or run["catalog_content_hash"] != catalog.catalog_content_hash
            or tuple(run["drug_concept_ids"]) != tuple(item.concept_id for item in scope.drugs)
            or tuple(run["adverse_event_concept_ids"])
            != tuple(item.concept_id for item in scope.adverse_reactions)
            or (run["start_date"], run["end_date"]) != dates
            or run["pubmed_query"] != expected_query
            or sum(
                item["run_id"] == run_id and item["manifest_id"] == snapshot_id
                for item in metadata.attempts
            )
            != 1
        ):
            raise PubMedMaterialStoreError("source material run or scope authority differs")
        return query_identity(scope, expected_query)

    def _verify_local_job_scope(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        snapshot_id: str,
        publication_version_id: str | None,
    ) -> str:
        """Use the separate canonical local job and persisted acquisition authority."""

        assert self._local_jobs is not None
        job = self._local_jobs.load(run_id)
        if job is None:
            raise PubMedMaterialStoreError("local research job is unavailable")
        raw_scope = job["scope_payload"]
        if type(raw_scope) is not dict:
            raise PubMedMaterialStoreError("local research job scope is invalid")
        try:
            exact_scope = ResearchScope.model_validate_json(canonical_json(raw_scope), strict=True)
            expected_query = build_pubmed_query(scope, catalog)
        except ValueError as error:
            raise PubMedMaterialStoreError(
                "local research job scope or query is invalid"
            ) from error
        if (
            exact_scope != scope
            or raw_scope != scope.model_dump(mode="json")
            or job["scope_id"] != scope.scope_id
            or job["scope_hash"] != sha256_digest(canonical_json(raw_scope))
            or job["run_id"] != run_id
            or job["phase"] == "submitted"
            or catalog.catalog_version != "m3.local-research-input.v1"
            or catalog.catalog_content_hash != LOCAL_RESEARCH_CATALOG_HASH
            or catalog.drugs != scope.drugs
            or catalog.adverse_reactions != scope.adverse_reactions
        ):
            raise PubMedMaterialStoreError("local research job is foreign or unstarted")
        search_query_id = query_identity(scope, expected_query)
        try:
            search_raw = self._snapshots.read_pubmed_search_progress(run_id)
            parsed_search = PubMedSearchProgressRecord.model_validate_json(search_raw)
            search = PubMedSearchProgressRecord.model_validate(
                parsed_search.model_dump(mode="python"), strict=True
            )
        except (ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise PubMedMaterialStoreError(
                "local PubMed search membership is unavailable"
            ) from error
        search_snapshot = self._repository.get_snapshot(search.snapshot_id)
        if (
            search.artifact_bytes() != search_raw
            or search.run_id != run_id
            or search.scope_id != scope.scope_id
            or search.query != expected_query
            or search.query_id != search_query_id
            or search_snapshot is None
            or search_snapshot.attempt is None
            or search_snapshot.attempt["run_id"] != run_id
            or search_snapshot.attempt["operation"] != "search"
            or search_snapshot.attempt["acquisition_ordinal"] != 0
            or search_snapshot.attempt["acquisition_intent_id"] != search.acquisition_intent_id
            or search_snapshot.snapshot["source"] != SourceType.PUBMED.value
            or search_snapshot.snapshot["request_identity"] != search_query_id
        ):
            raise PubMedMaterialStoreError("local PubMed search differs from job authority")
        snapshot = self._repository.get_snapshot(snapshot_id)
        matches = (
            ()
            if snapshot is None
            else tuple(
                row
                for row in snapshot.publications
                if row["publication_version_id"] == publication_version_id
            )
        )
        expected_fetch_identity = "pubmed:" + matches[0]["pmid"] if len(matches) == 1 else None
        if (
            snapshot is None
            or snapshot.attempt is None
            or expected_fetch_identity is None
            or matches[0]["pmid"] not in search.pmids
            or snapshot.attempt["run_id"] != run_id
            or snapshot.attempt["manifest_id"] != snapshot_id
            or snapshot.attempt["source"] != SourceType.PUBMED.value
            or snapshot.attempt["operation"] != "fetch"
            or snapshot.attempt["request_identity"] != expected_fetch_identity
            or snapshot.snapshot["source"] != SourceType.PUBMED.value
            or snapshot.snapshot["request_identity"] != expected_fetch_identity
            or snapshot.snapshot["acquisition_intent_id"]
            != snapshot.attempt["acquisition_intent_id"]
        ):
            raise PubMedMaterialStoreError("local PubMed acquisition differs from job authority")
        return expected_fetch_identity

    def _journal_bytes(self, identity: dict[str, str], selection: PubMedMaterialSelection) -> bytes:
        raw = canonical_json(
            {
                "schema_version": _SCHEMA,
                "identity": identity,
                "selection_hash": _selection_hash(selection),
            }
        ).encode("utf-8")
        if len(raw) > _MAX_JOURNAL_BYTES:
            raise PubMedMaterialStoreError("source material journal exceeds byte bound")
        return raw

    def materialize(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        publication: PublicationRecord,
        binding: PersistedPublicationBinding,
    ) -> PubMedMaterialSelection:
        run_id = TypeAdapter(RunId).validate_python(run_id, strict=True)
        scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        catalog = ResolvedConceptCatalog.model_validate(
            catalog.model_dump(mode="python"), strict=True
        )
        publication = PublicationRecord.model_validate(
            publication.model_dump(mode="python"), strict=True
        )
        binding = PersistedPublicationBinding.model_validate(
            binding.model_dump(mode="python"), strict=True
        )
        selected, trusted_publication, trusted_binding = self._selection(
            run_id=run_id,
            scope=scope,
            catalog=catalog,
            publication_version_id=publication.publication_version_id,
            snapshot_id=binding.snapshot_id,
        )
        if (
            publication.version_payload() != trusted_publication.version_payload()
            or publication.publication_version_id != trusted_publication.publication_version_id
            or publication.content_hash != trusted_publication.content_hash
            or publication.provenance.snapshot_id != binding.snapshot_id
            or publication.provenance.artifact_ids != binding.artifact_ids
            or publication.provenance.transformation_lineage
            != (publication.content_hash, binding.snapshot_id)
            or binding != trusted_binding
        ):
            raise PubMedMaterialStoreError("caller publication differs from source replay")
        identity = _identity(
            run_id=run_id,
            scope_id=scope.scope_id,
            publication_version_id=publication.publication_version_id,
            snapshot_id=binding.snapshot_id,
        )
        raw = self._journal_bytes(identity, selected)
        relative = _relative_path(identity)
        try:
            if self._snapshots.has_writer_lock:
                self._snapshots.publish_bytes(relative, raw, artifact_class="journal")
                self._provenance.publish_pubmed(
                    PubMedSourceCaptureProof(
                        trusted_publication, trusted_binding, selected.source_reference
                    )
                )
            else:
                with self._snapshots.writer():
                    self._snapshots.publish_bytes(relative, raw, artifact_class="journal")
                    self._provenance.publish_pubmed(
                        PubMedSourceCaptureProof(
                            trusted_publication, trusted_binding, selected.source_reference
                        )
                    )
        except (ValueError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise PubMedMaterialStoreError("source material publication failed") from error
        loaded = self.load_verified_selection(
            run_id=run_id,
            scope=scope,
            catalog=catalog,
            publication_version_id=publication.publication_version_id,
            snapshot_id=binding.snapshot_id,
        )
        if loaded != selected:
            raise PubMedMaterialStoreError("published source material readback differs")
        return loaded

    def load_verified_selection(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        catalog: ResolvedConceptCatalog,
        publication_version_id: str,
        snapshot_id: str,
    ) -> PubMedMaterialSelection | None:
        run_id = TypeAdapter(RunId).validate_python(run_id, strict=True)
        scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        catalog = ResolvedConceptCatalog.model_validate(
            catalog.model_dump(mode="python"), strict=True
        )
        identity = _identity(
            run_id=run_id,
            scope_id=scope.scope_id,
            publication_version_id=publication_version_id,
            snapshot_id=snapshot_id,
        )
        target = self._snapshots.root.joinpath(*PurePosixPath(_relative_path(identity)).parts)
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=True)
            if not target.exists():
                return None
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= _MAX_JOURNAL_BYTES:
                raise PubMedMaterialStoreError("source material journal exceeds byte bound")
            with target.open("rb") as handle:
                raw = handle.read(size + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
        except (OSError, SnapshotContainmentError, SnapshotIntegrityError) as error:
            raise PubMedMaterialStoreError("source material journal is unavailable") from error
        recorded_hash = _decode_record(raw, identity)
        selected, publication, _ = self._selection(
            run_id=run_id,
            scope=scope,
            catalog=catalog,
            publication_version_id=publication_version_id,
            snapshot_id=snapshot_id,
        )
        if _selection_hash(selected) != recorded_hash:
            raise PubMedMaterialStoreError("source material selection differs from journal")
        evidence = selected.source_reference
        try:
            verified = self._provenance.load_verified_provenance(
                run_id=run_id,
                evidence_id=evidence.evidence_id,
                source=SourceType.PUBMED,
                source_record_id=publication.pmid,
                source_version=publication_version_id,
                snapshot_id=snapshot_id,
                content_hash=publication.content_hash,
            )
        except EvidenceProvenanceIntegrityError as error:
            raise PubMedMaterialStoreError("source material provenance replay failed") from error
        if verified is None or verified.evidence_id != evidence.evidence_id:
            raise PubMedMaterialStoreError("source material has no verified provenance anchor")
        return selected
