"""Immutable, bounded pre-semantic validation registry for dynamic jobs."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import final

from pydantic import TypeAdapter

from medevidence.domain import derive_identity, sha256_digest
from medevidence.ingestion.snapshots import (
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.orchestration.contracts import RuntimeContext, ValidationRegistryRef
from medevidence.tools.report_validation import (
    M3_VALIDATION_CONFIGURATION_V2,
    M3_VALIDATION_CONFIGURATION_V3,
    M3_VALIDATION_CONFIGURATION_V4,
    ClaimInclusion,
    PlannedStage2SemanticInputV2,
    ValidationRegistryInput,
    _copy_registry,
    _registry_has_duplicate_identity,
)

from .report_material_codec import ReportMaterialError, _decode, _encode

_MAX_REGISTRY_BYTES = 2_097_152
_ADAPTER: TypeAdapter[ValidationRegistryInput] = TypeAdapter(ValidationRegistryInput)


class ValidationRegistryStoreError(ValueError):
    """The pre-semantic registry or its immutable authority is unavailable."""


def _relative_path(content_hash: str) -> str:
    digest = content_hash.removeprefix("sha256:")
    return f"m3/validation-registry/sha256/{digest[:2]}/{digest}.json"


def _registry_bytes(value: ValidationRegistryInput) -> bytes:
    if type(value) is not ValidationRegistryInput:
        raise ValidationRegistryStoreError("registry must use its exact canonical type")
    if value.configuration_version not in (
        M3_VALIDATION_CONFIGURATION_V2,
        M3_VALIDATION_CONFIGURATION_V3,
        M3_VALIDATION_CONFIGURATION_V4,
    ) or any(
        type(item) is not PlannedStage2SemanticInputV2 for item in value.semantic_expectations
    ):
        raise ValidationRegistryStoreError("dynamic registry is not a V2 pre-semantic plan")
    claim_ids = {item.claim_id for item in value.claims}
    evidence_ids = {item.evidence_id for item in value.evidence}
    formal_ids = {item.claim_id for item in value.claims if item.inclusion is ClaimInclusion.FORMAL}
    if (
        _registry_has_duplicate_identity(value)
        or any(
            item.claim_id not in claim_ids or item.evidence_id not in evidence_ids
            for item in value.citations
        )
        or any(item.authorized_run_id != value.run_id for item in value.evidence)
        or any(
            claim.citation_ids
            != tuple(
                item.citation_id for item in value.citations if item.claim_id == claim.claim_id
            )
            for claim in value.claims
        )
        or tuple(item.citation_id for item in value.semantic_expectations)
        != tuple(item.citation_id for item in value.citations if item.claim_id in formal_ids)
    ):
        raise ValidationRegistryStoreError("dynamic registry reference graph is incomplete")
    try:
        copied = _copy_registry(value)
        raw = _encode(copied).encode("utf-8")
        if len(raw) > _MAX_REGISTRY_BYTES or _decode(raw.decode("utf-8"), _ADAPTER) != copied:
            raise ValidationRegistryStoreError("registry exceeds canonical typed bound")
    except (ReportMaterialError, ValueError) as error:
        raise ValidationRegistryStoreError("registry violates its closed typed contract") from error
    return raw


@final
class SnapshotValidationRegistryStore:
    """Publish after synthesis and reparse exact bytes on every validation/resume."""

    def __init__(self, snapshots: SnapshotStore) -> None:
        self._snapshots = snapshots

    def publish_registry(
        self,
        *,
        context: RuntimeContext,
        report_content_hash: str,
        registry: ValidationRegistryInput,
    ) -> ValidationRegistryRef:
        if type(context) is not RuntimeContext:
            raise ValidationRegistryStoreError("runtime context must be exact")
        context = RuntimeContext.model_validate(context.model_dump(mode="python"), strict=True)
        if registry.run_id != context.run_id or registry.scope_id != context.scope_id:
            raise ValidationRegistryStoreError("registry belongs to another runtime context")
        raw = _registry_bytes(registry)
        content_hash = sha256_digest(raw)
        reference = ValidationRegistryRef(
            run_id=context.run_id,
            report_id=context.report_id,
            scope_id=context.scope_id,
            report_content_hash=report_content_hash,
            registry_content_hash=content_hash,
            registry_id=derive_identity(
                "validation-registry",
                {
                    "run_id": context.run_id,
                    "report_id": context.report_id,
                    "scope_id": context.scope_id,
                    "report_content_hash": report_content_hash,
                    "registry_content_hash": content_hash,
                },
            ),
        )
        relative = _relative_path(content_hash)
        if self._snapshots.has_writer_lock:
            self._snapshots.publish_bytes(relative, raw, artifact_class="journal")
        else:
            with self._snapshots.writer():
                self._snapshots.publish_bytes(relative, raw, artifact_class="journal")
        if self.load_registry(reference) != registry:
            raise ValidationRegistryStoreError("published registry readback differs")
        return reference

    def load_registry(self, reference: ValidationRegistryRef) -> ValidationRegistryInput:
        if type(reference) is not ValidationRegistryRef:
            raise ValidationRegistryStoreError("registry reference must be exact")
        try:
            reference = ValidationRegistryRef.model_validate(
                reference.model_dump(mode="python"), strict=True
            )
            relative = _relative_path(reference.registry_content_hash)
            target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            size = target.stat().st_size
            if not 1 <= size <= _MAX_REGISTRY_BYTES:
                raise ValidationRegistryStoreError("registry byte size exceeds bound")
            self._snapshots._verify_file(
                target,
                reference.registry_content_hash.removeprefix("sha256:"),
                size,
            )
            with target.open("rb") as handle:
                raw = handle.read(_MAX_REGISTRY_BYTES + 1)
            self._snapshots._require_safe_path(target, allow_missing_leaf=False)
            if len(raw) != size or sha256_digest(raw) != reference.registry_content_hash:
                raise ValidationRegistryStoreError("registry changed during read")
            decoded = _decode(raw.decode("utf-8"), _ADAPTER)
            if _registry_bytes(decoded) != raw:
                raise ValidationRegistryStoreError("registry bytes differ after reconstruction")
            if decoded.run_id != reference.run_id or decoded.scope_id != reference.scope_id:
                raise ValidationRegistryStoreError("registry payload belongs to another job")
            return decoded
        except (
            OSError,
            SnapshotContainmentError,
            SnapshotIntegrityError,
            ReportMaterialError,
            ValueError,
        ) as error:
            raise ValidationRegistryStoreError(
                "registry bytes or context are unavailable"
            ) from error
