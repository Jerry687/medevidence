"""Durable, reference-only CADEC material from the exact approved local asset."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self, final

from pydantic import model_validator

from medevidence.domain import (
    CADEC_ARCHIVE_SHA256,
    CADEC_EXTERNAL_MANIFEST_SHA256,
    CADEC_RECOVERY_MANIFEST_SHA256,
    ResearchScope,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.identifiers import DurableModel
from medevidence.ingestion.snapshots import SnapshotError, SnapshotStore
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    RequiredSourceOperation,
    SourceOperationKind,
    SourceTaskAttemptRef,
    SourceTaskFailureRef,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
    TerminalSourceOperationResult,
)
from medevidence.orchestration.source_capabilities import (
    collect_cadec_capability,
    terminal_source_task,
)
from medevidence.orchestration.source_task_projection import source_operation_observation
from medevidence.tools.cadec_runtime import (
    CadecDocumentEvidenceRef,
    CadecLocalSearchPlan,
    CadecRuntimeError,
    CadecSearchResult,
    plan_cadec_local_search,
    reconstruct_cadec_search_result,
)
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.report_validation import EvidenceInput, canonical_evidence_id

from .cadec_local_search import (
    CadecLocalSearchAdapter,
    CanonicalCadecEvidenceCollection,
    _FrozenSlots,
)
from .local_source_runtime import VerifiedSourceMaterial

_MAX_RECEIPT_BYTES = 131_072
_MAX_INDEX_BYTES = 1_024
_SOURCE_VERSION = f"m1b.cadec.archive.sha256.{CADEC_ARCHIVE_SHA256}"


class CadecMaterialError(ValueError):
    """An exact CADEC receipt, checkpoint, or asset cannot be reverified."""


def _material(
    run_id: str,
    snapshot_id: str,
    item: CadecDocumentEvidenceRef,
    at: datetime,
    *,
    manifest_sha256: str = CADEC_EXTERNAL_MANIFEST_SHA256,
) -> VerifiedSourceMaterial:
    if manifest_sha256 not in (CADEC_EXTERNAL_MANIFEST_SHA256, CADEC_RECOVERY_MANIFEST_SHA256):
        raise CadecMaterialError("CADEC material requires one closed manifest profile")
    if at.tzinfo is None or at.utcoffset() is None:
        raise CadecMaterialError("CADEC retrieval time is not UTC aware")
    at = at.astimezone(UTC)
    # The source document is never copied. An empty permission set prevents this
    # registry entry from becoming a clinical or methodological claim premise.
    provisional = EvidenceInput(
        evidence_id="pending",
        authorized_run_id=run_id,
        source=SourceType.CADEC,
        source_record_id=item.document_record_id,
        source_version=_SOURCE_VERSION,
        snapshot_id=snapshot_id,
        content_hash=item.content_sha256,
        locators=(item.locator_ref,),
        permitted_claim_classes=frozenset(),
        permitted_inference_uses=frozenset(),
        normalized_excerpt=(
            f"CADEC auxiliary document reference {item.document_id}; "
            f"local retrieval {at.isoformat()}"
        ),
        numerical_facts=(),
    )
    evidence = replace(provisional, evidence_id=canonical_evidence_id(provisional))
    provenance = EvidenceProvenanceV1(
        evidence_id=evidence.evidence_id,
        source=SourceType.CADEC,
        source_record_id=evidence.source_record_id,
        source_version=evidence.source_version,
        snapshot_id=snapshot_id,
        content_hash=evidence.content_hash,
        source_url=None,
        lookup_key=item.member_path,
        retrieved_at=at,
        transformation_lineage=(
            f"approved archive sha256:{CADEC_ARCHIVE_SHA256}",
            f"approved manifest sha256:{manifest_sha256}",
            f"exact member {item.member_sha256}",
            f"split membership {item.split_membership_sha256}",
            f"whole-document locator {item.locator_ref}",
            "metadata-only auxiliary reference; no corpus text or claim permission",
        ),
    )
    return VerifiedSourceMaterial(evidence=evidence, provenance=provenance)


class _Receipt(DurableModel):
    schema_version: Literal["m3.cadec.reference-material-receipt.v1"] = (
        "m3.cadec.reference-material-receipt.v1"
    )
    run_id: str
    scope: ResearchScope
    scope_id: str
    task_id: str
    attempt_id: str
    retrieved_at_utc: datetime
    search_result: CadecSearchResult
    legacy_collection: CollectedEvidenceResult

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        offset = self.retrieved_at_utc.utcoffset()
        if (
            self.retrieved_at_utc.tzinfo is None
            or offset is None
            or offset.total_seconds() != 0
            or self.scope.scope_id != self.scope_id
            or SourceType.CADEC not in self.scope.selected_sources
            or self.search_result.scope_id != self.scope_id
            or self.legacy_collection.attempt.attempt_id != self.attempt_id
            or self.legacy_collection.attempt.task_id != self.task_id
            or len(self.legacy_collection.required_operations) != 2
            or self.legacy_collection.required_operations[0].run_id != self.run_id
            or len(self.legacy_collection.operation_results) != 2
            or self.legacy_collection.operation_results[1].operation.kind
            is not SourceOperationKind.CADEC_SEARCH
        ):
            raise ValueError("CADEC material receipt is foreign or incomplete")
        return self


class _Index(DurableModel):
    schema_version: Literal["m3.cadec.reference-material-index.v1"] = (
        "m3.cadec.reference-material-index.v1"
    )
    run_id: str
    evidence_id: str
    scope_id: str
    task_id: str
    attempt_id: str
    receipt_hash: str


def _receipt_path(run_id: str, scope_id: str, task_id: str, attempt_id: str) -> str:
    digest = derive_identity(
        "cadec-material-receipt",
        (run_id, scope_id, task_id, attempt_id),
    ).removeprefix("cadec-material-receipt:sha256:")
    return f"cadec/material/{digest[:2]}/{digest}.json"


def _index_path(run_id: str, evidence_id: str) -> str:
    digest = derive_identity("cadec-material-index", (run_id, evidence_id)).removeprefix(
        "cadec-material-index:sha256:"
    )
    return f"cadec/material-index/{digest[:2]}/{digest}.json"


class _FixedSearch:
    def __init__(self, exact: CadecSearchResult) -> None:
        self._exact = exact

    def search(self, *, plan: CadecLocalSearchPlan, scope: ResearchScope) -> CadecSearchResult:
        return reconstruct_cadec_search_result(self._exact, scope=scope, plan=plan)


def _canonical_collection(receipt: _Receipt) -> CollectedEvidenceResult:
    original = receipt.legacy_collection
    search = original.operation_results[1]
    items = receipt.search_result.evidence_refs
    if len(search.observations) != len(items):
        raise CadecMaterialError("CADEC search observations differ from exact asset references")
    expected_legacy = tuple(derive_identity("cadec-document-evidence", item) for item in items)
    if tuple(item.evidence_id for item in search.observations) != expected_legacy:
        raise CadecMaterialError("CADEC original references differ from exact asset")
    materials = tuple(
        _material(
            receipt.run_id,
            search.acquisition.snapshot_id,
            item,
            receipt.retrieved_at_utc,
            manifest_sha256=receipt.search_result.verification.manifest_sha256,
        )
        for item in items
    )
    observations = tuple(
        source_operation_observation(
            operation=search.operation,
            acquisition=search.acquisition,
            evidence_id=material.evidence.evidence_id,
            content_hash=material.evidence.content_hash,
            locator_ref=material.evidence.locators[0],
        )
        for material in materials
    )
    projected_search = TerminalSourceOperationResult(
        operation=search.operation,
        attempt=search.attempt,
        acquisition=search.acquisition,
        outcome=search.outcome,
        observations=observations,
    )
    operations = (original.operation_results[0], projected_search)
    return CollectedEvidenceResult(
        attempt=original.attempt,
        required_operations=original.required_operations,
        operation_results=operations,
        terminal_outcome_ref=original.terminal_outcome_ref,
        evidence_refs=tuple(item.evidence_reference for item in observations),
        limitations=original.limitations,
    )


@final
class CadecMaterialRuntime(_FrozenSlots):
    """Collect canonical CADEC references and replay one immutable metadata receipt."""

    __slots__ = ("_delegate", "_search", "_snapshots", "_utc_now")
    _delegate: CanonicalCadecEvidenceCollection
    _search: CadecLocalSearchAdapter
    _snapshots: SnapshotStore
    _utc_now: Callable[[], datetime]

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("CadecMaterialRuntime is a sealed infrastructure adapter")

    def __init__(
        self,
        *,
        delegate: CanonicalCadecEvidenceCollection,
        snapshots: SnapshotStore,
        archive_path: Path,
        manifest_path: Path,
        manifest_sha256: str = CADEC_EXTERNAL_MANIFEST_SHA256,
        utc_now: Callable[[], datetime],
    ) -> None:
        if (
            type(delegate) is not CanonicalCadecEvidenceCollection
            or type(snapshots) is not SnapshotStore
        ):
            raise TypeError("CADEC material requires exact source and snapshot authorities")
        object.__setattr__(self, "_delegate", delegate)
        object.__setattr__(self, "_snapshots", snapshots)
        object.__setattr__(
            self,
            "_search",
            CadecLocalSearchAdapter(
                archive_path=archive_path,
                manifest_path=manifest_path,
                manifest_sha256=manifest_sha256,
            ),
        )
        object.__setattr__(self, "_utc_now", utc_now)
        _FrozenSlots._freeze(self)

    def plan_operations(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> tuple[RequiredSourceOperation, ...]:
        return self._delegate.plan_operations(task, scope, attempt)

    def collect(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> CollectedEvidenceResult | SourceTaskFailureRef | SourceTaskProgressResult:
        if task.source is not SourceType.CADEC:
            return self._delegate.collect(task, scope, attempt)
        self.plan_operations(task, scope, attempt)
        run_id = task.required_operations[0].run_id
        relative = _receipt_path(run_id, scope.scope_id, task.task_id, attempt.attempt_id)
        if (self._snapshots.root / relative).exists():
            receipt = self._read_receipt(run_id, scope, task, attempt.attempt_id)
            if task.required_operations != receipt.legacy_collection.required_operations:
                raise CadecMaterialError("CADEC repeated attempt plan differs from receipt")
            self._replay_original(receipt)
            projected = _canonical_collection(receipt)
            self._publish_indexes(receipt, projected)
            return projected
        try:
            exact = self._search.search(
                plan=plan_cadec_local_search(scope, manifest_sha256=self._search._manifest_sha256),
                scope=scope,
            )
        except CadecRuntimeError:
            return self._delegate.collect(task, scope, attempt)
        original = collect_cadec_capability(
            task=task,
            scope=scope,
            attempt=attempt,
            search=_FixedSearch(exact),
            manifest_sha256=self._search._manifest_sha256,
        )
        now = self._utc_now()
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            raise CadecMaterialError("CADEC retrieval clock must return UTC-aware time")
        receipt = _Receipt(
            run_id=original.required_operations[0].run_id,
            scope=scope,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            retrieved_at_utc=now.astimezone(UTC),
            search_result=exact,
            legacy_collection=original,
        )
        projected = _canonical_collection(receipt)
        raw = canonical_json(receipt).encode("utf-8")
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise CadecMaterialError("CADEC metadata receipt exceeds its byte cap")
        if self._snapshots.has_writer_lock:
            self._snapshots.publish_bytes(relative, raw, artifact_class="journal")
        else:
            with self._snapshots.writer():
                self._snapshots.publish_bytes(relative, raw, artifact_class="journal")
        if self._read_receipt(receipt.run_id, scope, task, attempt.attempt_id) != receipt:
            raise CadecMaterialError("CADEC material receipt changed during publication")
        self._publish_indexes(receipt, projected)
        return projected

    def _publish_indexes(self, receipt: _Receipt, projected: CollectedEvidenceResult) -> None:
        receipt_hash = sha256_digest(canonical_json(receipt))
        records = tuple(
            (
                _index_path(receipt.run_id, item.evidence_id),
                canonical_json(
                    _Index(
                        run_id=receipt.run_id,
                        evidence_id=item.evidence_id,
                        scope_id=receipt.scope_id,
                        task_id=receipt.task_id,
                        attempt_id=receipt.attempt_id,
                        receipt_hash=receipt_hash,
                    )
                ).encode("utf-8"),
            )
            for item in projected.evidence_refs
        )
        if any(len(raw) > _MAX_INDEX_BYTES for _path, raw in records):
            raise CadecMaterialError("CADEC material index exceeds its byte cap")

        def write() -> None:
            for relative, raw in records:
                self._snapshots.publish_bytes(relative, raw, artifact_class="journal")

        if self._snapshots.has_writer_lock:
            write()
        else:
            with self._snapshots.writer():
                write()

    def _read_receipt(
        self, run_id: str, scope: ResearchScope, task: SourceTaskState, attempt_id: str
    ) -> _Receipt:
        relative = _receipt_path(run_id, scope.scope_id, task.task_id, attempt_id)
        target = self._snapshots.root / relative
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= _MAX_RECEIPT_BYTES:
                raise CadecMaterialError("CADEC material receipt byte size is invalid")
            with target.open("rb") as handle:
                raw = handle.read(_MAX_RECEIPT_BYTES + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            if len(raw) != size:
                raise CadecMaterialError("CADEC material receipt changed during read")
            receipt = _Receipt.model_validate_json(raw)
            if canonical_json(receipt).encode("utf-8") != raw:
                raise CadecMaterialError("CADEC material receipt is noncanonical")
        except (OSError, ValueError, SnapshotError) as error:
            raise CadecMaterialError("CADEC material receipt unavailable or invalid") from error
        if (
            receipt.run_id != run_id
            or receipt.scope != scope
            or receipt.scope_id != scope.scope_id
            or receipt.task_id != task.task_id
            or receipt.attempt_id != attempt_id
        ):
            raise CadecMaterialError("CADEC material receipt belongs to another task")
        reconstruct_cadec_search_result(
            receipt.search_result,
            scope=scope,
            plan=plan_cadec_local_search(scope, manifest_sha256=self._search._manifest_sha256),
        )
        if receipt.search_result.outcome != receipt.legacy_collection.operation_results[1].outcome:
            raise CadecMaterialError("CADEC material receipt outcome differs")
        return receipt

    def _read_index(self, run_id: str, evidence_id: str) -> _Index | None:
        target = self._snapshots.root / _index_path(run_id, evidence_id)
        if not target.exists():
            return None
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= _MAX_INDEX_BYTES:
                raise CadecMaterialError("CADEC material index byte size is invalid")
            with target.open("rb") as handle:
                raw = handle.read(_MAX_INDEX_BYTES + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            if len(raw) != size:
                raise CadecMaterialError("CADEC material index changed during read")
            index = _Index.model_validate_json(raw)
            if canonical_json(index).encode("utf-8") != raw:
                raise CadecMaterialError("CADEC material index is noncanonical")
        except (OSError, ValueError, SnapshotError) as error:
            raise CadecMaterialError("CADEC material index unavailable or invalid") from error
        if index.run_id != run_id or index.evidence_id != evidence_id:
            raise CadecMaterialError("CADEC material index belongs to another reference")
        return index

    def _replay_original(self, receipt: _Receipt) -> None:
        scope = receipt.scope
        exact = self._search.search(
            plan=plan_cadec_local_search(scope, manifest_sha256=self._search._manifest_sha256),
            scope=scope,
        )
        if exact != receipt.search_result:
            raise CadecMaterialError("CADEC approved asset differs from material receipt")
        attempt = receipt.legacy_collection.attempt
        running = SourceTaskState(
            task_id=receipt.task_id,
            source=SourceType.CADEC,
            required_operations=receipt.legacy_collection.required_operations,
            status=SourceTaskStatus.RUNNING,
            attempts=attempt.attempt_number,
            active_attempt=attempt,
        )
        replayed = collect_cadec_capability(
            task=running,
            scope=scope,
            attempt=attempt,
            search=_FixedSearch(exact),
            manifest_sha256=self._search._manifest_sha256,
        )
        if replayed != receipt.legacy_collection:
            raise CadecMaterialError("CADEC original collection differs from exact asset replay")

    def validate_terminal_task(self, task: SourceTaskState, scope: ResearchScope) -> None:
        if task.source is not SourceType.CADEC:
            self._delegate.validate_terminal_task(task, scope)
            return
        if task.status is not SourceTaskStatus.TERMINAL or len(task.operation_results) != 2:
            raise CadecMaterialError("CADEC material replay requires a complete terminal task")
        if not task.operation_results[1].observations and (
            task.operation_results[1].outcome.execution_status.value != "succeeded"
        ):
            self._delegate.validate_terminal_task(task, scope)
            return
        attempt = task.operation_results[0].attempt
        run_id = task.required_operations[0].run_id
        receipt = self._read_receipt(run_id, scope, task, attempt.attempt_id)
        running = SourceTaskState(
            task_id=task.task_id,
            source=task.source,
            required_operations=task.required_operations,
            status=SourceTaskStatus.RUNNING,
            attempts=task.attempts,
            active_attempt=attempt,
            failure_history=task.failure_history,
        )
        legacy_terminal = terminal_source_task(running, receipt.legacy_collection, run_id)
        self._delegate.validate_terminal_task(legacy_terminal, scope)
        canonical_terminal = terminal_source_task(running, _canonical_collection(receipt), run_id)
        if task != canonical_terminal:
            raise CadecMaterialError("CADEC terminal task differs from durable material replay")

    def read_material(
        self,
        run_id: str,
        scope: ResearchScope,
        task: SourceTaskState,
        terminal_search_result: TerminalSourceOperationResult,
    ) -> tuple[VerifiedSourceMaterial, ...]:
        self.validate_terminal_task(task, scope)
        if task.operation_results[1] != terminal_search_result:
            raise CadecMaterialError("CADEC material read has another terminal search")
        attempt_id = terminal_search_result.attempt.attempt_id
        receipt = self._read_receipt(run_id, scope, task, attempt_id)
        return tuple(
            _material(
                run_id,
                terminal_search_result.acquisition.snapshot_id,
                item,
                receipt.retrieved_at_utc,
                manifest_sha256=receipt.search_result.verification.manifest_sha256,
            )
            for item in receipt.search_result.evidence_refs
        )

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
        """Reverify one indexed auxiliary reference against the original asset."""
        if source is not SourceType.CADEC:
            return None
        index = self._read_index(run_id, evidence_id)
        if index is None:
            return None
        scope = self._read_index_scope(index)
        task = SourceTaskState(task_id=index.task_id, source=SourceType.CADEC)
        receipt = self._read_receipt(run_id, scope, task, index.attempt_id)
        if sha256_digest(canonical_json(receipt)) != index.receipt_hash:
            raise CadecMaterialError("CADEC index differs from its immutable receipt")
        self._replay_original(receipt)
        projected = _canonical_collection(receipt)
        for item, reference in zip(
            receipt.search_result.evidence_refs, projected.evidence_refs, strict=True
        ):
            if reference.evidence_id != evidence_id:
                continue
            material = _material(
                run_id,
                receipt.legacy_collection.operation_results[1].acquisition.snapshot_id,
                item,
                receipt.retrieved_at_utc,
                manifest_sha256=receipt.search_result.verification.manifest_sha256,
            )
            evidence = material.evidence
            if (
                evidence.source_record_id == source_record_id
                and evidence.source_version == source_version
                and evidence.snapshot_id == snapshot_id
                and evidence.content_hash == content_hash
            ):
                return material.provenance
            return None
        raise CadecMaterialError("CADEC index does not name a receipt evidence reference")

    def _read_index_scope(self, index: _Index) -> ResearchScope:
        """Resolve only the exact receipt whose scope identity the index names."""
        relative = _receipt_path(index.run_id, index.scope_id, index.task_id, index.attempt_id)
        target = self._snapshots.root / relative
        try:
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= _MAX_RECEIPT_BYTES:
                raise CadecMaterialError("CADEC indexed receipt byte size is invalid")
            with target.open("rb") as handle:
                raw = handle.read(_MAX_RECEIPT_BYTES + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            if len(raw) != size:
                raise CadecMaterialError("CADEC indexed receipt changed during read")
            receipt = _Receipt.model_validate_json(raw)
            if canonical_json(receipt).encode("utf-8") != raw:
                raise CadecMaterialError("CADEC indexed receipt is noncanonical")
        except (OSError, ValueError, SnapshotError) as error:
            raise CadecMaterialError("CADEC indexed receipt unavailable or invalid") from error
        if receipt.scope_id != index.scope_id or receipt.scope.scope_id != index.scope_id:
            raise CadecMaterialError("CADEC indexed scope differs from receipt")
        return receipt.scope


__all__ = ["CadecMaterialError", "CadecMaterialRuntime"]
